import 'dart:async';
import 'dart:math' as math;

import 'package:dio/dio.dart';
import 'package:flutter/widgets.dart';

import '../api/api_client.dart';
import '../models/chat_models.dart';
import 'auth_store.dart';
import 'cloud_connections.dart';

class OutboxMessage {
  OutboxMessage({
    required this.id,
    required this.text,
    required this.images,
    this.files = const [],
  });

  final String id;
  final String text;
  final List<ChatImage> images;
  final List<ChatFile> files;
  final DateTime sentAt = DateTime.now();
  String? error;

  bool posted = false;
}

class ResolvedRequest {
  const ResolvedRequest(this.request, this.answer);

  final ChatRequest request;
  final Object? answer;
}

class ChatStore extends ChangeNotifier {
  ChatStore({required this.auth}) : cloud = CloudConnections(auth) {
    _current = _draft();
  }

  final AuthStore auth;

  final CloudConnections cloud;

  ApiClient get api => auth.api;

  final List<ChatSession> _sessions = [];
  late ChatSession _current;
  final Map<String, List<OutboxMessage>> _outbox = {};
  final Map<String, Map<String, ResolvedRequest>> _resolved = {};
  final Set<String> _answering = {};

  StreamSubscription<Map<String, dynamic>>? _stream;
  CancelToken? _cancel;
  Timer? _retry;
  int _attempt = 0;
  int _idSeed = 0;
  bool _disposed = false;

  String? listError;
  bool listLoaded = false;

  ChatSession get current => _current;

  List<ChatSession> get history =>
      [..._sessions]..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));

  List<OutboxMessage> outboxOf(String sessionId) =>
      _outbox[sessionId] ?? const [];

  ResolvedRequest? resolvedFor(String sessionId, String? callId) =>
      callId == null ? null : _resolved[sessionId]?[callId];

  bool isAnswering(String requestId) => _answering.contains(requestId);

  bool isTyping(String sessionId) {
    if (sessionId != _current.id) return false;
    final session = _current;
    if (session.waiting) return false;
    if (!session.running && outboxOf(sessionId).isEmpty) return false;
    final last = session.lastMessage;
    if (last != null &&
        last.role == ChatRole.assistant &&
        last.inProgress &&
        last.text.isNotEmpty) {
      return false;
    }
    return true;
  }

  String _nextId(String prefix) =>
      '$prefix-${DateTime.now().microsecondsSinceEpoch}-${_idSeed++}';

  ChatSession _draft() => ChatSession(
    id: _nextId('draft'),
    title: ChatSession.untitled,
    createdAt: DateTime.now(),
  )..loaded = true;

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> start() async {
    await refreshList();
    if (_current.remote) _openStream(_current);
  }

  void reset() {
    _closeStream();
    _sessions.clear();
    _outbox.clear();
    _resolved.clear();
    listLoaded = false;
    listError = null;
    _current = _draft();
    _notify();
  }

  void pause() => _closeStream();

  Future<void> refreshList() async {
    try {
      final result = await api.get('/api/chats');
      final incoming = [
        for (final json in Json.list(result['chats']))
          ChatSession.fromJson(json),
      ];
      final byId = {for (final s in _sessions) s.id: s};
      final seen = <String>{};
      for (final item in incoming) {
        seen.add(item.id);
        final existing = byId[item.id];
        if (existing == null) {
          _sessions.add(item);
        } else {
          existing
            ..title = item.title
            ..preview = item.preview
            ..updatedAt = item.updatedAt;
          if (existing != _current) existing.running = item.running;
        }
      }
      _sessions.removeWhere((s) => !seen.contains(s.id));
      if (_current.remote && !seen.contains(_current.id)) {
        _closeStream();
        _current = _draft();
      }
      listError = null;
      listLoaded = true;
    } on ApiException catch (error) {
      listError = error.message;
    }
    _notify();
  }

  void startNewSession() {
    if (!_current.remote && _current.isEmpty && outboxOf(_current.id).isEmpty) {
      return;
    }
    _closeStream();
    _current = _draft();
    _notify();
  }

  void select(String sessionId) {
    if (_current.id == sessionId) return;
    final match = _sessions.where((s) => s.id == sessionId);
    if (match.isEmpty) return;
    _closeStream();
    _current = match.first;
    _openStream(_current);
    _notify();
  }

  Future<void> open(String sessionId) async {
    if (!_sessions.any((s) => s.id == sessionId)) await refreshList();
    select(sessionId);
  }

  Future<void> delete(String sessionId) async {
    final session = _sessions.where((s) => s.id == sessionId).firstOrNull;
    if (session == null) return;
    await api.delete('/api/chats/$sessionId');
    _sessions.remove(session);
    _outbox.remove(sessionId);
    _resolved.remove(sessionId);
    if (_current.id == sessionId) {
      _closeStream();
      _current = _draft();
    }
    _notify();
  }

  Future<void> send(
    String rawText, {
    List<ChatImage> images = const [],
    List<ChatFile> files = const [],
  }) async {
    final text = rawText.trim();
    if (text.isEmpty && images.isEmpty && files.isEmpty) return;

    var session = _current;
    final pending = OutboxMessage(
      id: _nextId('local'),
      text: text,
      images: images,
      files: files,
    );
    _outbox.putIfAbsent(session.id, () => []).add(pending);
    session.updatedAt = DateTime.now();
    if (session.hasDefaultTitle && text.isNotEmpty) {
      session.title = _titleFrom(text);
    }
    _notify();

    try {
      if (!session.remote) {
        final created = ChatSession.fromJson(await api.post('/api/chats'));
        created.title = session.title;
        _outbox[created.id] = _outbox.remove(session.id) ?? [];
        _sessions.add(created);
        if (_current == session) {
          _current = created;
          _openStream(created);
        }
        session = created;
      }
      await api.post('/api/chats/${session.id}/messages', {
        'text': text,
        'attachments': [
          for (final image in images) image.uploadId,
          for (final file in files) file.uploadId,
        ].whereType<String>().toList(),
      });
      pending.posted = true;
      final shown = session.messages.any(
        (m) =>
            m.isUser &&
            m.text == text &&
            !m.sentAt.isBefore(
              pending.sentAt.subtract(const Duration(seconds: 5)),
            ),
      );
      if (shown) _outbox[session.id]?.remove(pending);
      session.preview = text.isNotEmpty
          ? 'You: $text'
          : files.isNotEmpty
          ? 'You: ${files.first.name}'
          : 'You: Photo';
      session.updatedAt = DateTime.now();
      _notify();
    } on ApiException catch (error) {
      pending.error = error.message;
      _notify();
      rethrow;
    }
  }

  void discard(OutboxMessage message) {
    for (final list in _outbox.values) {
      list.remove(message);
    }
    _notify();
  }

  Future<void> stop() async {
    final session = _current;
    if (!session.remote) return;
    await api.post('/api/chats/${session.id}/stop');
  }

  Future<void> answer(ChatRequest request, Object? value) async {
    final session = _current;
    if (_answering.contains(request.id)) return;
    _answering.add(request.id);
    _notify();
    try {
      await api.post('/api/chats/${session.id}/requests/${request.id}', {
        'value': value,
      });
      _resolve(session, request.id, value);
    } on ApiException catch (error) {
      if (error.status == 409) {
        _resolve(session, request.id, null);
        return;
      }
      rethrow;
    } finally {
      _answering.remove(request.id);
      _notify();
    }
  }

  void _resolve(ChatSession session, String requestId, Object? answer) {
    final index = session.requests.indexWhere((r) => r.id == requestId);
    if (index < 0) return;
    final request = session.requests.removeAt(index);
    if (request.callId != null && answer != null) {
      _resolved.putIfAbsent(session.id, () => {})[request.callId!] =
          ResolvedRequest(request, answer);
    }
  }

  static String _titleFrom(String text) {
    final singleLine = text.replaceAll(RegExp(r'\s+'), ' ');
    if (singleLine.length <= 32) return singleLine;
    return '${singleLine.substring(0, 32).trimRight()}…';
  }

  void _openStream(ChatSession session) {
    _closeStream();
    if (!session.remote || _disposed) return;
    final cancel = CancelToken();
    _cancel = cancel;
    _stream = api
        .events('/api/chats/${session.id}/stream', cancel: cancel)
        .listen(
          (event) => _apply(session, event),
          onError: (Object _) => _scheduleRetry(session, cancel),
          onDone: () => _scheduleRetry(session, cancel),
          cancelOnError: true,
        );
  }

  void _closeStream() {
    _retry?.cancel();
    _retry = null;
    _cancel?.cancel();
    _cancel = null;
    _stream?.cancel();
    _stream = null;
  }

  void _scheduleRetry(ChatSession session, CancelToken token) {
    if (_disposed || token.isCancelled || session != _current) return;
    _attempt++;
    final seconds = math.min(15, 1 << math.min(_attempt, 4));
    _retry?.cancel();
    _retry = Timer(Duration(seconds: seconds), () {
      if (session == _current && !_disposed) _openStream(session);
    });
  }

  void _apply(ChatSession session, Map<String, dynamic> event) {
    switch (event['type']) {
      case 'snapshot':
        _attempt = 0;
        session.messages
          ..clear()
          ..addAll([
            for (final json in Json.list(event['messages']))
              ChatMessage.fromJson(json),
          ]);
        session.messages.sort((a, b) => a.sentAt.compareTo(b.sentAt));
        session.requests
          ..clear()
          ..addAll([
            for (final json in Json.list(event['requests']))
              ChatRequest.fromJson(json),
          ]);
        session.running = event['activity'] == 'running';
        session.lastError = session.running ? null : event['error'] as String?;
        session.queued = (event['queued'] as num?)?.toInt() ?? 0;
        session.loaded = true;
        final chat = event['chat'];
        if (chat is Map && chat['title'] is String) {
          session.title = chat['title'] as String;
        }
        final outbox = _outbox[session.id];
        if (outbox != null) {
          final posted = outbox.where((m) => m.posted && m.error == null);
          final drop = posted.length - session.queued;
          if (drop > 0) {
            final stale = posted.take(drop).toSet();
            outbox.removeWhere(stale.contains);
          }
        }
      case 'message':
        final json = event['message'];
        if (json is! Map) return;
        final message = ChatMessage.fromJson(json.cast<String, dynamic>());
        final isNew = _upsert(session, message);
        if (isNew && message.role == ChatRole.user) {
          final outbox = _outbox[session.id];
          final index = outbox?.indexWhere((m) => m.error == null) ?? -1;
          if (index >= 0) outbox!.removeAt(index);
        }
      case 'delta':
        final id = event['id'] as String?;
        final text = (event['text'] as String?) ?? '';
        if (id == null) return;
        final index = session.messages.indexWhere((m) => m.id == id);
        if (index < 0) {
          session.messages.add(
            ChatMessage(
              id: id,
              role: ChatRole.assistant,
              text: text,
              sentAt: DateTime.now(),
              status: 'in_progress',
            ),
          );
        } else if (session.messages[index].inProgress) {
          final current = session.messages[index];
          session.messages[index] = current.copyWith(text: current.text + text);
        }
      case 'thinking':
        final index = session.messages.indexWhere((m) => m.id == event['id']);
        if (index >= 0 && !session.messages[index].thinking) {
          session.messages[index] = session.messages[index].copyWith(
            thinking: true,
          );
        }
      case 'patch':
        final index = session.messages.indexWhere((m) => m.id == event['id']);
        final changes = event['changes'];
        if (index >= 0 && changes is Map) {
          session.messages[index] = session.messages[index].copyWith(
            status: changes['status'] as String?,
            data: changes['data'],
          );
        }
      case 'request':
        final json = event['request'];
        if (json is! Map) return;
        final request = ChatRequest.fromJson(json.cast<String, dynamic>());
        session.requests.removeWhere((r) => r.id == request.id);
        session.requests.add(request);
      case 'request_closed':
        _resolve(session, event['id'] as String, event['answer']);
      case 'turn':
        final state = event['state'] as String?;
        session.running = state == 'running';
        if (state == 'running') {
          session.lastError = null;
        } else if (state == 'error') {
          final error = event['error'];
          session.lastError = error is Map
              ? (error['message'] as String?)
              : 'Something went wrong';
        }
        if (state != 'running') session.updatedAt = DateTime.now();
      case 'queue':
        session.queued = (event['count'] as num?)?.toInt() ?? 0;
      case 'reset':
        _openStream(session);
        return;
      default:
        return;
    }
    if (session == _current) _notify();
  }

  bool _upsert(ChatSession session, ChatMessage message) {
    final index = session.messages.indexWhere((m) => m.id == message.id);
    if (index >= 0) {
      session.messages[index] = message;
      return false;
    }
    var at = session.messages.length;
    while (at > 0 && session.messages[at - 1].sentAt.isAfter(message.sentAt)) {
      at--;
    }
    session.messages.insert(at, message);
    return true;
  }

  @override
  void dispose() {
    _disposed = true;
    _closeStream();
    cloud.dispose();
    super.dispose();
  }
}

class ChatScope extends InheritedNotifier<ChatStore> {
  const ChatScope({super.key, required ChatStore store, required super.child})
    : super(notifier: store);

  static ChatStore of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<ChatScope>();
    assert(scope != null, 'No ChatScope found in the widget tree.');
    return scope!.notifier!;
  }

  static ChatStore read(BuildContext context) {
    final scope = context.getInheritedWidgetOfExactType<ChatScope>();
    assert(scope != null, 'No ChatScope found in the widget tree.');
    return scope!.notifier!;
  }
}
