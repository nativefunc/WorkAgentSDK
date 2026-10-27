import 'dart:async';
import 'dart:math' as math;

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'activity_store.dart';
import 'auth_store.dart';
import 'chat_store.dart';

class AppEvents {
  AppEvents({required this.auth, required this.chats, required this.activity});

  final AuthStore auth;
  final ChatStore chats;
  final ActivityStore activity;

  StreamSubscription<Map<String, dynamic>>? _subscription;
  CancelToken? _cancel;
  Timer? _retry;
  int _attempt = 0;
  bool _running = false;

  void start() {
    if (_running) return;
    _running = true;
    _attempt = 0;
    _connect();
  }

  void stop() {
    _running = false;
    _retry?.cancel();
    _cancel?.cancel();
    _subscription?.cancel();
    _subscription = null;
  }

  void _connect() {
    if (!_running || !auth.api.hasToken) return;
    final cancel = CancelToken();
    _cancel = cancel;
    _subscription = auth.api
        .events('/api/events', cancel: cancel)
        .listen(
          _handle,
          onError: (Object _) => _reconnect(cancel),
          onDone: () => _reconnect(cancel),
          cancelOnError: true,
        );
  }

  void _reconnect(CancelToken cancel) {
    if (!_running || cancel.isCancelled) return;
    _attempt++;
    _retry?.cancel();
    _retry = Timer(
      Duration(seconds: math.min(20, 1 << math.min(_attempt, 4))),
      _connect,
    );
  }

  void _handle(Map<String, dynamic> event) {
    switch (event['type']) {
      case 'hello':
        _attempt = 0;
        unawaited(chats.refreshList());
        unawaited(activity.refresh());
        unawaited(auth.refresh());
      case 'chats':
        unawaited(chats.refreshList());
      case 'activity':
        unawaited(activity.refresh());
      case 'device':
        unawaited(auth.refresh());
      default:
        debugPrint('OpenMuse: unknown event ${event['type']}');
    }
  }
}
