import 'package:flutter/foundation.dart';

import 'auth_store.dart';

enum CloudKind { computer, browser, workspace }

enum CloudState { connecting, connected, offline, disconnected }

extension CloudKindSetting on CloudKind {
  String get settingKey => switch (this) {
    CloudKind.computer => 'computer',
    CloudKind.browser => 'browser',
    CloudKind.workspace => 'workspace',
  };

  bool get canTakeControl => this != CloudKind.workspace;
}

class CloudConnection extends ValueNotifier<CloudState> {
  CloudConnection._(this.kind, this._owner) : super(CloudState.disconnected);

  final CloudKind kind;
  final CloudConnections _owner;

  bool get isConnected => value == CloudState.connected;

  void connect() => _owner._setEnabled(kind, true);

  void disconnect() => _owner._setEnabled(kind, false);
}

class CloudConnections {
  CloudConnections(this.auth) {
    computer = CloudConnection._(CloudKind.computer, this);
    browser = CloudConnection._(CloudKind.browser, this);
    workspace = CloudConnection._(CloudKind.workspace, this);
    auth.addListener(_sync);
    _sync();
  }

  final AuthStore auth;
  late final CloudConnection computer;
  late final CloudConnection browser;
  late final CloudConnection workspace;

  final Set<CloudKind> _saving = {};

  final ValueNotifier<String?> error = ValueNotifier(null);

  List<CloudConnection> get all => [computer, browser, workspace];

  Listenable get listenable => Listenable.merge([...all, error]);

  bool get paired => auth.device.paired;
  bool get online => auth.device.online;

  CloudConnection of(CloudKind kind) => switch (kind) {
    CloudKind.computer => computer,
    CloudKind.browser => browser,
    CloudKind.workspace => workspace,
  };

  bool _enabled(CloudKind kind) => switch (kind) {
    CloudKind.computer => auth.settings.computer,
    CloudKind.browser => auth.settings.browser,
    CloudKind.workspace => auth.settings.workspace,
  };

  void _sync() {
    for (final connection in all) {
      if (_saving.contains(connection.kind)) continue;
      if (!_enabled(connection.kind)) {
        connection.value = CloudState.disconnected;
      } else if (!paired || !online) {
        connection.value = CloudState.offline;
      } else {
        connection.value = CloudState.connected;
      }
    }
  }

  Future<void> _setEnabled(CloudKind kind, bool enabled) async {
    if (_saving.contains(kind)) return;
    _saving.add(kind);
    error.value = null;
    of(kind).value = CloudState.connecting;
    try {
      await auth.updateSettings({kind.settingKey: enabled});
    } catch (e) {
      error.value = e.toString();
    } finally {
      _saving.remove(kind);
      _sync();
    }
  }

  CloudState get overall {
    final states = all.map((c) => c.value);
    if (states.contains(CloudState.connecting)) return CloudState.connecting;
    if (states.contains(CloudState.connected)) return CloudState.connected;
    if (states.contains(CloudState.offline)) return CloudState.offline;
    return CloudState.disconnected;
  }

  void dispose() {
    auth.removeListener(_sync);
    for (final c in all) {
      c.dispose();
    }
    error.dispose();
  }
}
