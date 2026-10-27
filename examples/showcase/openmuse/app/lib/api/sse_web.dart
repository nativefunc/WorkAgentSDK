import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

Stream<Map<String, dynamic>>? openEventStream(String url) {
  web.EventSource? source;
  late final StreamController<Map<String, dynamic>> controller;
  controller = StreamController<Map<String, dynamic>>(
    onListen: () {
      final events = web.EventSource(url);
      source = events;
      events.onmessage = ((web.MessageEvent event) {
        final data = event.data;
        if (!data.isA<JSString>()) return;
        final decoded = jsonDecode((data as JSString).toDart);
        if (decoded is Map<String, dynamic>) controller.add(decoded);
      }).toJS;
      events.onerror = ((web.Event _) {
        events.close();
        if (!controller.isClosed) {
          controller.addError(StateError('The event stream closed'));
          controller.close();
        }
      }).toJS;
    },
    onCancel: () => source?.close(),
  );
  return controller.stream;
}
