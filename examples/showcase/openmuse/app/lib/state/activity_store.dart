import 'package:flutter/widgets.dart';

import '../api/api_client.dart';
import '../models/chat_models.dart';
import 'auth_store.dart';

class ActivityStore extends ChangeNotifier {
  ActivityStore({required this.auth});

  final AuthStore auth;

  ApiClient get api => auth.api;

  List<PendingItem> needsYou = const [];
  List<RunningItem> running = const [];
  List<Routine> routines = const [];
  List<RunItem> recent = const [];

  bool loading = false;
  bool loaded = false;
  String? error;
  bool _disposed = false;
  bool _again = false;

  int get attentionCount => needsYou.length;

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> refresh() async {
    if (loading) {
      _again = true;
      return;
    }
    loading = true;
    _notify();
    try {
      final result = await api.get('/api/activity');
      needsYou = [
        for (final json in Json.list(result['needs_you']))
          PendingItem(
            chatId: json['chat_id'] as String,
            chatTitle: (json['chat_title'] as String?) ?? '',
            request: ChatRequest.fromJson(
              (json['request'] as Map).cast<String, dynamic>(),
            ),
          ),
      ];
      running = [
        for (final json in Json.list(result['running']))
          RunningItem(
            chatId: json['chat_id'] as String,
            chatTitle: (json['chat_title'] as String?) ?? '',
            source: (json['source'] as String?) ?? 'user',
            startedAt: Json.time(json['started_at']),
            step: json['step'] as String?,
          ),
      ];
      routines = [
        for (final json in Json.list(result['scheduled']))
          Routine.fromJson(json),
      ];
      recent = [
        for (final json in Json.list(result['recent'])) RunItem.fromJson(json),
      ];
      error = null;
      loaded = true;
    } on ApiException catch (e) {
      error = e.message;
    } finally {
      loading = false;
      _notify();
    }
    if (_again) {
      _again = false;
      await refresh();
    }
  }

  void reset() {
    needsYou = const [];
    running = const [];
    routines = const [];
    recent = const [];
    loaded = false;
    error = null;
    _notify();
  }

  Future<void> routineAction(Routine routine, String action) async {
    await api.post('/api/schedules/${routine.id}/$action');
    await refresh();
  }

  Future<void> deleteRoutine(Routine routine) async {
    await api.delete('/api/schedules/${routine.id}');
    routines = routines.where((r) => r.id != routine.id).toList();
    _notify();
    await refresh();
  }

  Future<Routine> createRoutine({
    required String prompt,
    required String repeat,
    required String time,
    String? date,
    int weekday = 1,
  }) async {
    final result = await api.post('/api/routines', {
      'prompt': prompt,
      'repeat': repeat,
      'time': time,
      if (date != null) 'date': date,
      'weekday': weekday,
    });
    await refresh();
    return Routine.fromJson(result);
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

class ActivityScope extends InheritedNotifier<ActivityStore> {
  const ActivityScope({
    super.key,
    required ActivityStore activity,
    required super.child,
  }) : super(notifier: activity);

  static ActivityStore of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<ActivityScope>();
    assert(scope != null, 'No ActivityScope found in the widget tree.');
    return scope!.notifier!;
  }

  static ActivityStore read(BuildContext context) {
    final scope = context.getInheritedWidgetOfExactType<ActivityScope>();
    assert(scope != null, 'No ActivityScope found in the widget tree.');
    return scope!.notifier!;
  }
}
