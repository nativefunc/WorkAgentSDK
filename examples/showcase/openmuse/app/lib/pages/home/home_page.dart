import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:file_picker/file_picker.dart';

import '../../api/api_client.dart';
import '../../glass/glass_toast.dart';
import '../../models/chat_models.dart';
import '../../state/chat_store.dart';
import '../../theme/app_theme.dart';
import '../../utils/tool_labels.dart';
import '../remote/take_control_page.dart';
import 'widgets/attach_sheet.dart';
import 'widgets/chat_header.dart';
import 'widgets/composer.dart';
import 'widgets/connections_sheet.dart';
import 'widgets/message_bubble.dart';
import 'widgets/notices.dart';
import 'widgets/request_cards.dart';
import 'widgets/session_panel.dart';
import 'widgets/step_group.dart';
import 'widgets/welcome_view.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final TextEditingController _input = TextEditingController();
  final FocusNode _inputFocus = FocusNode();
  final ScrollController _scroll = ScrollController();

  final List<PendingAttachment> _attachments = [];

  static const int _maxAttachments = 6;

  static const int _maxFileBytes = 20 * 1024 * 1024;

  String? _lastSignature;
  String? _lastSessionId;

  bool _pinned = true;

  bool _userScrolling = false;

  bool _jumpOnLoad = true;

  static const double _composerHeight = 52;

  bool _sidebarOpen = true;

  static const Color _sidebarColor = Color(0xFFF7F7F8);

  @override
  void dispose() {
    _input.dispose();
    _inputFocus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send([String? text]) async {
    final value = text ?? _input.text;
    if (_attachments.any((a) => a.uploading)) return;
    final images = [
      for (final a in _attachments)
        if (a.uploaded && a.isImage)
          ChatImage(uploadId: a.uploadId, bytes: a.bytes),
    ];
    final files = [
      for (final a in _attachments)
        if (a.uploaded && !a.isImage)
          ChatFile(uploadId: a.uploadId, name: a.name, size: a.size),
    ];
    if (value.trim().isEmpty && images.isEmpty && files.isEmpty) return;
    _pinned = true;
    if (text == null) _input.clear();
    setState(_attachments.clear);
    try {
      await ChatScope.read(context).send(value, images: images, files: files);
    } on ApiException catch (error) {
      if (mounted) {
        showGlassToast(
          context,
          error.message,
          icon: Icons.error_outline_rounded,
        );
      }
    }
  }

  Future<void> _retry(OutboxMessage message) async {
    final store = ChatScope.read(context);
    store.discard(message);
    try {
      await store.send(
        message.text,
        images: message.images,
        files: message.files,
      );
    } on ApiException catch (error) {
      if (mounted) {
        showGlassToast(
          context,
          error.message,
          icon: Icons.error_outline_rounded,
        );
      }
    }
  }

  Future<void> _stop() async {
    try {
      await ChatScope.read(context).stop();
    } on ApiException catch (error) {
      if (mounted) {
        showGlassToast(
          context,
          error.message,
          icon: Icons.error_outline_rounded,
        );
      }
    }
  }

  Future<void> _onAttach() async {
    _inputFocus.unfocus();
    final room = _maxAttachments - _attachments.length;
    if (room <= 0) {
      showGlassToast(
        context,
        'Up to $_maxAttachments attachments per message',
        icon: Icons.info_outline_rounded,
      );
      return;
    }
    final source = await showAttachSheet(context);
    if (!mounted || source == null) return;
    List<PlatformFile> picked;
    try {
      picked = source == AttachSource.photos
          ? await FilePicker.pickFiles(
              type: FileType.image,
              darwinOptions: const DarwinOptions(
                assetRepresentationMode:
                    DarwinAssetRepresentationMode.compatible,
              ),
            )
          : await FilePicker.pickFiles();
    } catch (error) {
      if (mounted) {
        showGlassToast(
          context,
          source == AttachSource.photos
              ? "Couldn't open your photos"
              : "Couldn't open your files",
          icon: Icons.error_outline_rounded,
        );
      }
      return;
    }
    if (!mounted || picked.isEmpty) return;
    var added = 0;
    var tooLarge = 0;
    for (final file in picked.take(room)) {
      final size = file.lengthSync() ?? await file.length() ?? 0;
      if (size > _maxFileBytes) {
        tooLarge++;
        continue;
      }
      final bytes = await file.readAsBytes();
      if (!mounted) return;
      if (bytes.isEmpty) continue;
      final attachment = PendingAttachment(bytes: bytes, name: file.name);
      setState(() => _attachments.add(attachment));
      unawaited(_upload(attachment));
      added++;
    }
    if (tooLarge > 0) {
      showGlassToast(
        context,
        tooLarge == 1
            ? 'That file is over 20 MB'
            : '$tooLarge files are over 20 MB',
        icon: Icons.error_outline_rounded,
      );
    }
    if (added > 0) _revealLastMessage();
  }

  void _revealLastMessage() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _scrollToEnd(animate: true);
    });
  }

  Future<void> _upload(PendingAttachment attachment) async {
    final api = ChatScope.read(context).api;
    try {
      final result = await api.uploadFile(
        attachment.bytes,
        attachment.name,
        onProgress: (p) {
          if (mounted) setState(() => attachment.progress = p);
        },
      );
      if (mounted) {
        setState(() => attachment.uploadId = result['id'] as String?);
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => attachment.error = error.message);
      showGlassToast(context, error.message, icon: Icons.error_outline_rounded);
    }
  }

  Future<void> _answer(ChatRequest request, Object? value) async {
    try {
      await ChatScope.read(context).answer(request, value);
    } on ApiException catch (error) {
      if (mounted) {
        showGlassToast(
          context,
          error.message,
          icon: Icons.error_outline_rounded,
        );
      }
    }
  }

  void _takeOver(ChatRequest request) {
    final store = ChatScope.read(context);
    final connection = request.data['target'] == 'computer'
        ? store.cloud.computer
        : store.cloud.browser;
    showTakeControl(
      context,
      connection,
      chatId: store.current.id,
      request: request,
    );
  }

  void _openSessions() {
    _inputFocus.unfocus();
    showSessionPanel(context);
  }

  void _onMenu(bool wide) {
    if (wide) {
      setState(() => _sidebarOpen = !_sidebarOpen);
    } else {
      _openSessions();
    }
  }

  void _scrollToEnd({required bool animate}) {
    if (!_scroll.hasClients) return;
    final position = _scroll.positions.last;
    final target = position.maxScrollExtent;
    if (animate) {
      position
          .animateTo(
            target,
            duration: const Duration(milliseconds: 320),
            curve: Curves.easeOutCubic,
          )
          .then((_) => _settleAtEnd(position, 0));
    } else {
      position.jumpTo(target);
      _settleAtEnd(position, 0);
    }
  }

  void _settleAtEnd(ScrollPosition position, int attempt) {
    if (attempt >= 12) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_pinned || _userScrolling) return;
      if (!_scroll.positions.contains(position)) return;
      final target = position.maxScrollExtent;
      if (position.pixels < target - 0.5) position.jumpTo(target);
      _settleAtEnd(position, attempt + 1);
    });
  }

  void _followConversation(ChatStore store) {
    final session = store.current;
    final last = session.lastMessage;
    final signature =
        '${session.id}:${session.messages.length}:${last?.text.length}:'
        '${session.requests.length}:${store.outboxOf(session.id).length}:${store.isTyping(session.id)}';
    if (signature == _lastSignature) return;

    if (session.id != _lastSessionId) {
      _pinned = true;
      _userScrolling = false;
      _jumpOnLoad = true;
    }
    _lastSignature = signature;
    _lastSessionId = session.id;
    final jump = _jumpOnLoad;
    if (session.loaded || !session.remote) _jumpOnLoad = false;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_pinned) return;
      _scrollToEnd(animate: !jump);
    });
  }

  @override
  Widget build(BuildContext context) {
    final store = ChatScope.of(context);
    _followConversation(store);

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = AppLayout.isWide(constraints.maxWidth);
        final sidebarVisible = wide && _sidebarOpen;
        final chat = _buildChat(
          context,
          store,
          wide: wide,
          sidebarVisible: sidebarVisible,
        );
        if (!wide) return chat;

        return Row(
          children: [
            AnimatedContainer(
              key: const ValueKey('chat-sidebar'),
              duration: const Duration(milliseconds: 280),
              curve: Curves.easeOutCubic,
              width: sidebarVisible ? AppLayout.sidebarWidth : 0,
              decoration: BoxDecoration(
                color: _sidebarColor,
                border: sidebarVisible
                    ? const Border(
                        right: BorderSide(
                          color: AppColors.hairline,
                          width: 0.5,
                        ),
                      )
                    : null,
              ),
              child: ClipRect(
                child: OverflowBox(
                  alignment: Alignment.topRight,
                  minWidth: AppLayout.sidebarWidth,
                  maxWidth: AppLayout.sidebarWidth,
                  child: SessionBrowser(
                    embedded: true,
                    bottomInset: AppLayout.contentBottomInset(context),
                    onOpen: (s) => store.select(s.id),
                    onNewChat: store.startNewSession,
                  ),
                ),
              ),
            ),
            Expanded(child: chat),
          ],
        );
      },
    );
  }

  Widget _buildChat(
    BuildContext context,
    ChatStore store, {
    required bool wide,
    required bool sidebarVisible,
  }) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final side = AppLayout.centeredInset(
          constraints.maxWidth,
          AppLayout.readableWidth,
        );
        final columnWidth = constraints.maxWidth - side * 2;
        return _buildChatColumn(
          context,
          store,
          side: side,
          columnWidth: columnWidth,
          wide: wide,
          sidebarVisible: sidebarVisible,
        );
      },
    );
  }

  Widget _buildChatColumn(
    BuildContext context,
    ChatStore store, {
    required double side,
    required double columnWidth,
    required bool wide,
    required bool sidebarVisible,
  }) {
    final session = store.current;
    final padding = MediaQuery.paddingOf(context);
    final keyboard = MediaQuery.viewInsetsOf(context).bottom;
    final keyboardOpen = keyboard > 0;
    final empty = session.isEmpty && store.outboxOf(session.id).isEmpty;

    final topInset = padding.top + ChatHeader.height + 8;
    final composerBottom = keyboardOpen
        ? keyboard + 8
        : AppLayout.tabBarHeight + AppLayout.tabBarBottomGap(context) + 10;
    final extras = _attachments.isNotEmpty ? Composer.extrasSpace : 0.0;
    final contentBottom = composerBottom + _composerHeight + extras + 20;

    return Stack(
      children: [
        Positioned.fill(
          child: AnimatedSwitcher(
            duration: const Duration(milliseconds: 260),
            child: empty
                ? WelcomeView(
                    key: ValueKey('welcome-${session.id}'),
                    topInset: topInset,
                    bottomInset: contentBottom,
                    onSuggestion: _send,
                  )
                : NotificationListener<ScrollNotification>(
                    key: ValueKey('list-${session.id}'),
                    onNotification: (notification) {
                      if (notification is UserScrollNotification) {
                        if (notification.direction != ScrollDirection.idle) {
                          _userScrolling = true;
                        }
                      } else if (_userScrolling &&
                          (notification is ScrollUpdateNotification ||
                              notification is ScrollEndNotification)) {
                        _pinned = notification.metrics.extentAfter < 80;
                        if (notification is ScrollEndNotification) {
                          _userScrolling = false;
                        }
                      }
                      return false;
                    },
                    child: _MessageList(
                      store: store,
                      session: session,
                      controller: _scroll,
                      columnWidth: columnWidth,
                      onAnswer: _answer,
                      onTakeOver: _takeOver,
                      onRetry: _retry,
                      padding: EdgeInsets.fromLTRB(
                        side,
                        topInset,
                        side,
                        contentBottom,
                      ),
                    ),
                  ),
          ),
        ),

        Positioned(
          top: 0,
          left: 0,
          right: 0,
          height: topInset + 8,
          child: const _EdgeFade(fromTop: true),
        ),
        Positioned(
          bottom: 0,
          left: 0,
          right: 0,
          height: composerBottom + _composerHeight * 0.6,
          child: const _EdgeFade(fromTop: false),
        ),

        Positioned(
          top: 0,
          left: 0,
          right: 0,
          child: ChatHeader(
            cloud: store.cloud,
            menuIcon: wide ? Icons.view_sidebar_outlined : Icons.notes_rounded,
            onMenu: () => _onMenu(wide),
            onConnections: () {
              _inputFocus.unfocus();
              showConnectionsSheet(
                context,
                store.cloud,
                chatId: session.remote ? session.id : null,
              );
            },
            onNewChat: () {
              _inputFocus.unfocus();
              store.startNewSession();
            },
          ),
        ),

        AnimatedPositioned(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOutCubic,
          left: side,
          right: side,
          bottom: composerBottom,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Composer(
                controller: _input,
                focusNode: _inputFocus,
                onSend: _send,
                onAttach: _onAttach,
                running: session.running,
                onStop: session.remote ? _stop : null,
                attachments: _attachments,
                onRemoveAttachment: (a) =>
                    setState(() => _attachments.remove(a)),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

sealed class _Entry {
  const _Entry();
}

class _BubbleEntry extends _Entry {
  const _BubbleEntry(this.message);
  final ChatMessage message;
}

class _OutboxEntry extends _Entry {
  const _OutboxEntry(this.message);
  final OutboxMessage message;
}

class _StepsEntry extends _Entry {
  _StepsEntry(this.key);
  final String key;
  final List<ChatMessage> steps = [];
}

class _NoticeEntry extends _Entry {
  const _NoticeEntry(this.message);
  final ChatMessage message;
}

class _RequestEntry extends _Entry {
  const _RequestEntry(this.request);
  final ChatRequest request;
}

class _TypingEntry extends _Entry {
  const _TypingEntry(this.label);
  final String? label;
}

class _ErrorEntry extends _Entry {
  const _ErrorEntry(this.message);
  final String message;
}

class _MessageList extends StatelessWidget {
  const _MessageList({
    required this.store,
    required this.session,
    required this.controller,
    required this.padding,
    required this.columnWidth,
    required this.onAnswer,
    required this.onTakeOver,
    required this.onRetry,
  });

  final ChatStore store;
  final ChatSession session;
  final ScrollController controller;
  final EdgeInsets padding;

  final double columnWidth;

  final Future<void> Function(ChatRequest, Object?) onAnswer;
  final ValueChanged<ChatRequest> onTakeOver;
  final ValueChanged<OutboxMessage> onRetry;

  List<_Entry> _entries() {
    final entries = <_Entry>[];
    final openCalls = {for (final r in session.requests) r.callId};
    _StepsEntry? steps;
    for (final message in session.messages) {
      switch (message.role) {
        case ChatRole.user:
          steps = null;
          entries.add(_BubbleEntry(message));
        case ChatRole.assistant:
          if (message.text.trim().isEmpty) continue;
          steps = null;
          entries.add(_BubbleEntry(message));
        case ChatRole.tool:
          if (message.status == 'waiting' &&
              openCalls.contains(message.callId)) {
            continue;
          }
          if (steps == null) {
            steps = _StepsEntry(message.id);
            entries.add(steps);
          }
          steps.steps.add(message);
        case ChatRole.custom:
          if (!visibleNotices.contains(message.kind)) continue;
          entries.add(_NoticeEntry(message));
      }
    }
    for (final pending in store.outboxOf(session.id)) {
      entries.add(_OutboxEntry(pending));
    }
    for (final request in session.requests) {
      entries.add(_RequestEntry(request));
    }
    final lastEntry = entries.lastOrNull;
    final stepRunning =
        lastEntry is _StepsEntry && lastEntry.steps.last.inProgress;
    if (store.isTyping(session.id) && !stepRunning) {
      final step = session.messages.lastWhere(
        (m) => m.role == ChatRole.tool,
        orElse: () => ChatMessage(
          id: '',
          role: ChatRole.tool,
          text: '',
          sentAt: DateTime.now(),
        ),
      );
      entries.add(
        _TypingEntry(
          session.running && step.inProgress
              ? ToolLabel.activity(step.toolName)
              : null,
        ),
      );
    }
    if (!session.running && session.lastError != null) {
      entries.add(_ErrorEntry(session.lastError!));
    }
    return entries;
  }

  Map<String, String> _answers() {
    final answers = <String, String>{};
    for (final message in session.messages) {
      if (message.toolName != 'ask_user' || message.callId == null) continue;
      final resolved = store.resolvedFor(session.id, message.callId);
      final answer = resolved?.answer;
      if (answer is Map) {
        final picked = [
          ...((answer['selected'] as List?) ?? const []),
          answer['other'],
        ].whereType<String>().where((s) => s.trim().isNotEmpty);
        if (picked.isNotEmpty) {
          answers[message.callId!] = '→ ${picked.join(', ')}';
        }
      }
    }
    return answers;
  }

  @override
  Widget build(BuildContext context) {
    final entries = _entries();
    final answers = _answers();
    final now = DateTime.now();

    if (!session.loaded && entries.isEmpty) {
      return const Center(
        child: SizedBox(
          width: 22,
          height: 22,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: AppColors.inkTertiary,
          ),
        ),
      );
    }

    return ListView.builder(
      controller: controller,
      padding: padding,
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      itemCount: entries.length,
      itemBuilder: (context, index) {
        final entry = entries[index];
        final next = index + 1 < entries.length ? entries[index + 1] : null;
        switch (entry) {
          case _BubbleEntry(:final message):
            final nextMessage = next is _BubbleEntry ? next.message : null;
            final showTime =
                !message.inProgress &&
                (nextMessage == null ||
                    nextMessage.role != message.role ||
                    nextMessage.sentAt.difference(message.sentAt).inMinutes >=
                        5);
            return MessageBubble(
              key: ValueKey(message.id),
              message: message,
              columnWidth: columnWidth,
              showTime: showTime,
              now: now,
            );
          case _OutboxEntry(:final message):
            return MessageBubble(
              key: ValueKey(message.id),
              message: ChatMessage(
                id: message.id,
                role: ChatRole.user,
                text: message.text,
                sentAt: message.sentAt,
                images: message.images,
                files: message.files,
              ),
              columnWidth: columnWidth,
              showTime: false,
              now: now,
              sending: message.error == null,
              error: message.error,
              onRetry: () => onRetry(message),
              onDiscard: () => store.discard(message),
            );
          case _StepsEntry():
            final isLast =
                next == null || next is _TypingEntry || next is _RequestEntry;
            return StepGroup(
              key: ValueKey('steps-${entry.key}'),
              steps: entry.steps,
              active: isLast && session.running,
              answers: answers,
            );
          case _NoticeEntry(:final message):
            return NoticeView(
              key: ValueKey(message.id),
              message: message,
              columnWidth: columnWidth,
            );
          case _RequestEntry(:final request):
            return RequestCard(
              key: ValueKey(request.id),
              request: request,
              columnWidth: columnWidth,
              busy: store.isAnswering(request.id),
              onAnswer: (value) => onAnswer(request, value),
              onTakeOver: onTakeOver,
            );
          case _TypingEntry(:final label):
            return TypingBubble(label: label);
          case _ErrorEntry(:final message):
            return _TurnError(message: message);
        }
      },
    );
  }
}

class _TurnError extends StatelessWidget {
  const _TurnError({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.error_outline_rounded,
            size: 17,
            color: AppColors.danger,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Something went wrong: $message',
              maxLines: 4,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 13.5,
                height: 1.4,
                color: AppColors.danger,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _EdgeFade extends StatelessWidget {
  const _EdgeFade({required this.fromTop});

  final bool fromTop;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: fromTop ? Alignment.topCenter : Alignment.bottomCenter,
            end: fromTop ? Alignment.bottomCenter : Alignment.topCenter,
            colors: [
              AppColors.canvas.withValues(alpha: 0.94),
              AppColors.canvas.withValues(alpha: 0.75),
              AppColors.canvas.withValues(alpha: 0),
            ],
            stops: const [0, 0.55, 1],
          ),
        ),
      ),
    );
  }
}
