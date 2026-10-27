import 'package:flutter/foundation.dart';

enum ChatRole { user, assistant, tool, custom }

ChatRole _role(String? value) => switch (value) {
  'user' => ChatRole.user,
  'tool' => ChatRole.tool,
  'custom' => ChatRole.custom,
  _ => ChatRole.assistant,
};

DateTime _time(Object? seconds) {
  if (seconds is num) {
    return DateTime.fromMillisecondsSinceEpoch((seconds * 1000).round());
  }
  return DateTime.now();
}

@immutable
class ChatImage {
  const ChatImage({required this.uploadId, this.bytes});

  final String? uploadId;

  final Uint8List? bytes;
}

@immutable
class ChatFile {
  const ChatFile({
    required this.uploadId,
    required this.name,
    this.size = 0,
    this.mime = 'application/octet-stream',
  });

  factory ChatFile.fromJson(Map<String, dynamic> json) => ChatFile(
    uploadId: json['id'] as String?,
    name: (json['name'] as String?) ?? 'File',
    size: (json['size'] as num?)?.toInt() ?? 0,
    mime: (json['mime'] as String?) ?? 'application/octet-stream',
  );

  final String? uploadId;
  final String name;
  final int size;
  final String mime;

  String get detail {
    final dot = name.lastIndexOf('.');
    final ext = dot > 0 && dot < name.length - 1
        ? name.substring(dot + 1).toUpperCase()
        : '';
    return ext.isEmpty || ext.length > 6 ? sizeLabel : '$ext · $sizeLabel';
  }

  String get sizeLabel {
    if (size < 1024) return '$size B';
    if (size < 1024 * 1024) return '${(size / 1024).round()} KB';
    return '${(size / 1024 / 1024).toStringAsFixed(1)} MB';
  }
}

@immutable
class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    required this.sentAt,
    this.status = 'completed',
    this.turnId,
    this.images = const [],
    this.files = const [],
    this.toolName,
    this.callId,
    this.preview = '',
    this.output = '',
    this.hasImage = false,
    this.error,
    this.kind,
    this.data,
    this.thinking = false,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final role = _role(json['role'] as String?);
    return ChatMessage(
      id: json['id'] as String,
      role: role,
      text: (json['text'] as String?) ?? '',
      sentAt: _time(json['created_at']),
      status: (json['status'] as String?) ?? 'completed',
      turnId: json['turn_id'] as String?,
      images: [
        for (final image in (json['images'] as List?) ?? const [])
          if (image is Map) ChatImage(uploadId: image['id'] as String?),
      ],
      files: [
        for (final file in (json['files'] as List?) ?? const [])
          if (file is Map) ChatFile.fromJson(file.cast<String, dynamic>()),
      ],
      toolName: json['tool'] as String?,
      callId: json['call_id'] as String?,
      preview: (json['preview'] as String?) ?? '',
      output: (json['output'] as String?) ?? '',
      hasImage: json['has_image'] == true,
      error: json['error'] as String?,
      kind: json['kind'] as String?,
      data: json['data'],
      thinking: json['thinking'] == true,
    );
  }

  final String id;
  final ChatRole role;
  final String text;
  final DateTime sentAt;

  final String status;
  final String? turnId;

  final List<ChatImage> images;
  final List<ChatFile> files;

  final String? toolName;
  final String? callId;

  final String preview;
  final String output;
  final bool hasImage;

  final String? error;

  final String? kind;
  final Object? data;

  final bool thinking;

  bool get isUser => role == ChatRole.user;
  bool get inProgress => status == 'in_progress';
  bool get failed => status == 'failed' || (error != null && error!.isNotEmpty);

  ChatMessage copyWith({
    String? text,
    String? status,
    Object? data,
    bool? thinking,
  }) {
    return ChatMessage(
      id: id,
      role: role,
      text: text ?? this.text,
      sentAt: sentAt,
      status: status ?? this.status,
      turnId: turnId,
      images: images,
      files: files,
      toolName: toolName,
      callId: callId,
      preview: preview,
      output: output,
      hasImage: hasImage,
      error: error,
      kind: kind,
      data: data ?? this.data,
      thinking: thinking ?? this.thinking,
    );
  }
}

@immutable
class ChatRequest {
  const ChatRequest({
    required this.id,
    required this.type,
    required this.data,
    required this.createdAt,
    this.callId,
    this.sensitive = false,
  });

  factory ChatRequest.fromJson(Map<String, dynamic> json) => ChatRequest(
    id: json['id'] as String,
    type: json['type'] as String,
    data: (json['data'] as Map?)?.cast<String, dynamic>() ?? const {},
    createdAt: _time(json['created_at']),
    callId: json['call_id'] as String?,
    sensitive: json['sensitive'] == true,
  );

  final String id;

  final String type;
  final Map<String, dynamic> data;
  final DateTime createdAt;
  final String? callId;
  final bool sensitive;

  String get summary {
    switch (type) {
      case 'AskUser':
        return (data['question'] as String?) ?? 'Has a question';
      case 'Approval':
        return (data['title'] as String?) ?? 'Needs your approval';
      case 'AppAccess':
        final apps = [
          for (final app in (data['apps'] as List?) ?? const [])
            if (app is Map) app['name'],
        ].whereType<String>().join(', ');
        return apps.isEmpty ? 'Wants to use an app' : 'Wants to use $apps';
      case 'Takeover':
        return (data['reason'] as String?) ?? 'Needs you to take over';
      default:
        return 'Needs your answer';
    }
  }
}

class ChatSession {
  ChatSession({
    required this.id,
    required this.title,
    required this.createdAt,
    DateTime? updatedAt,
    List<ChatMessage>? messages,
    this.preview = '',
    this.remote = false,
  }) : updatedAt = updatedAt ?? createdAt,
       messages = messages ?? <ChatMessage>[];

  factory ChatSession.fromJson(Map<String, dynamic> json) => ChatSession(
    id: json['id'] as String,
    title: (json['title'] as String?) ?? untitled,
    createdAt: _time(json['created_at']),
    updatedAt: _time(json['updated_at']),
    preview: (json['preview'] as String?) ?? '',
    remote: true,
  )..running = json['activity'] == 'running';

  static const String untitled = 'New chat';

  final String id;
  String title;
  final DateTime createdAt;
  DateTime updatedAt;
  String preview;

  bool remote;

  final List<ChatMessage> messages;
  final List<ChatRequest> requests = [];

  bool running = false;

  int queued = 0;

  String? lastError;

  bool loaded = false;

  bool get isEmpty => messages.isEmpty && !remote;
  bool get hasDefaultTitle => title == untitled;
  bool get waiting => requests.isNotEmpty;

  ChatMessage? get lastMessage => messages.isEmpty ? null : messages.last;
}

@immutable
class Routine {
  const Routine({
    required this.id,
    required this.chatId,
    required this.chatTitle,
    required this.prompt,
    required this.kind,
    required this.paused,
    this.at,
    this.everyMinutes,
    this.daily,
    this.weekdays,
    this.nextRun,
    this.lastRun,
  });

  factory Routine.fromJson(Map<String, dynamic> json) => Routine(
    id: json['id'] as String,
    chatId: json['chat_id'] as String,
    chatTitle: (json['chat_title'] as String?) ?? '',
    prompt: (json['prompt'] as String?) ?? '',
    kind: (json['kind'] as String?) ?? 'daily',
    paused: json['paused'] == true,
    at: json['at'] == null ? null : _time(json['at']),
    everyMinutes: (json['every_minutes'] as num?)?.toInt(),
    daily: json['daily'] as String?,
    weekdays: [
      for (final day in (json['weekdays'] as List?) ?? const [])
        (day as num).toInt(),
    ],
    nextRun: json['next_run'] == null ? null : _time(json['next_run']),
    lastRun: json['last_run'] == null ? null : _time(json['last_run']),
  );

  final String id;
  final String chatId;
  final String chatTitle;
  final String prompt;

  final String kind;
  final bool paused;
  final DateTime? at;
  final int? everyMinutes;
  final String? daily;
  final List<int>? weekdays;
  final DateTime? nextRun;
  final DateTime? lastRun;

  static const List<String> _days = [
    'Mon',
    'Tue',
    'Wed',
    'Thu',
    'Fri',
    'Sat',
    'Sun',
  ];

  String get rule {
    switch (kind) {
      case 'once':
        return 'Once';
      case 'every':
        final minutes = everyMinutes ?? 60;
        if (minutes % 60 == 0) {
          final hours = minutes ~/ 60;
          return hours == 1 ? 'Every hour' : 'Every $hours hours';
        }
        return 'Every $minutes min';
      default:
        final time = daily ?? '';
        final days = weekdays ?? const [];
        if (days.isEmpty || days.length == 7) return 'Every day at $time';
        if (days.length == 5 && !days.contains(6) && !days.contains(7)) {
          return 'Every weekday at $time';
        }
        return 'Every ${days.map((d) => _days[(d - 1).clamp(0, 6)]).join(', ')} at $time';
    }
  }
}

@immutable
class PendingItem {
  const PendingItem({
    required this.chatId,
    required this.chatTitle,
    required this.request,
  });

  final String chatId;
  final String chatTitle;
  final ChatRequest request;
}

@immutable
class RunningItem {
  const RunningItem({
    required this.chatId,
    required this.chatTitle,
    required this.source,
    required this.startedAt,
    this.step,
  });

  final String chatId;
  final String chatTitle;

  final String source;
  final DateTime startedAt;

  final String? step;
}

@immutable
class RunItem {
  const RunItem({
    required this.turnId,
    required this.chatId,
    required this.chatTitle,
    required this.source,
    required this.status,
    required this.summary,
    required this.steps,
    required this.endedAt,
  });

  factory RunItem.fromJson(Map<String, dynamic> json) => RunItem(
    turnId: json['turn_id'] as String,
    chatId: json['chat_id'] as String,
    chatTitle: (json['chat_title'] as String?) ?? '',
    source: (json['source'] as String?) ?? 'user',
    status: (json['status'] as String?) ?? 'completed',
    summary: (json['summary'] as String?) ?? '',
    steps: (json['steps'] as num?)?.toInt() ?? 0,
    endedAt: _time(json['ended_at'] ?? json['started_at']),
  );

  final String turnId;
  final String chatId;
  final String chatTitle;
  final String source;

  final String status;
  final String summary;
  final int steps;
  final DateTime endedAt;

  bool get failed => status == 'error' || status == 'rejected';
}

class Json {
  Json._();

  static DateTime time(Object? seconds) => _time(seconds);

  static List<Map<String, dynamic>> list(Object? value) => [
    for (final item in (value as List?) ?? const [])
      if (item is Map) item.cast<String, dynamic>(),
  ];
}
