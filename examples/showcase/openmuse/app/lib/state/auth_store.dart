import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../api/api_client.dart';

enum AuthStatus { restoring, signedOut, signedIn }

@immutable
class Account {
  const Account({required this.id, required this.email, required this.name});

  factory Account.fromJson(Map<String, dynamic> json) => Account(
    id: (json['id'] as num).toInt(),
    email: (json['email'] as String?) ?? '',
    name: (json['name'] as String?) ?? '',
  );

  final int id;
  final String email;
  final String name;

  String get initials {
    final parts = name
        .trim()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty)
        .toList();
    if (parts.isEmpty) return email.isEmpty ? '?' : email[0].toUpperCase();
    if (parts.length == 1) {
      final word = parts.first;
      return word.substring(0, word.length >= 2 ? 2 : 1).toUpperCase();
    }
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }
}

@immutable
class AgentSettings {
  const AgentSettings({
    this.workspace = true,
    this.browser = true,
    this.computer = true,
    this.confirmShell = false,
    this.confirmSubmit = true,
  });

  factory AgentSettings.fromJson(Map<String, dynamic> json) => AgentSettings(
    workspace: json['workspace'] != false,
    browser: json['browser'] != false,
    computer: json['computer'] != false,
    confirmShell: json['confirm_shell'] == true,
    confirmSubmit: json['confirm_submit'] != false,
  );

  final bool workspace;
  final bool browser;
  final bool computer;

  final bool confirmShell;

  final bool confirmSubmit;
}

@immutable
class DeviceStatus {
  const DeviceStatus({
    this.name = '',
    this.paired = false,
    this.online = false,
    this.local = false,
  });

  factory DeviceStatus.fromJson(Map<String, dynamic> json) => DeviceStatus(
    name: (json['name'] as String?) ?? '',
    paired: json['paired'] == true,
    online: json['online'] == true,
    local: json['mode'] == 'local',
  );

  final String name;
  final bool paired;
  final bool online;

  final bool local;
}

class AuthStore extends ChangeNotifier {
  AuthStore({String? serverUrl})
    : api = ApiClient(baseUrl: serverUrl ?? defaultServer) {
    api.onUnauthorized = _expired;
  }

  static String get defaultServer {
    const fromBuild = String.fromEnvironment('OPENMUSE_SERVER');
    if (fromBuild.isNotEmpty) return fromBuild;
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://127.0.0.1:8000';
  }

  static const _storage = FlutterSecureStorage();
  static const _tokenKey = 'openmuse.token';

  static const _serverKey = 'openmuse.server';

  final ApiClient api;

  AuthStatus _status = AuthStatus.restoring;
  Account? _account;
  AgentSettings _settings = const AgentSettings();
  DeviceStatus _device = const DeviceStatus();

  AuthStatus get status => _status;
  bool get isSignedIn => _status == AuthStatus.signedIn;
  Account? get account => _account;
  AgentSettings get settings => _settings;
  DeviceStatus get device => _device;
  String get serverUrl => api.baseUrl;

  Future<void> restore() async {
    try {
      await _storage.delete(key: _serverKey);
      api.token = await _storage.read(key: _tokenKey);
    } catch (_) {
      api.token = null;
    }
    if (!api.hasToken) {
      _set(AuthStatus.signedOut);
      return;
    }
    try {
      _apply(await api.get('/api/me'));
      _set(AuthStatus.signedIn);
    } on ApiException catch (error) {
      if (error.unauthorized) {
        await _forget();
      } else {
        _set(AuthStatus.signedIn);
      }
    }
  }

  Future<void> signIn({required String email, required String password}) async {
    final result = await api.post('/api/auth/login', {
      'email': email,
      'password': password,
    });
    await _signedIn(result);
  }

  Future<void> register({
    required String name,
    required String email,
    required String password,
  }) async {
    final result = await api.post('/api/auth/register', {
      'name': name,
      'email': email,
      'password': password,
    });
    await _signedIn(result);
  }

  Future<void> _signedIn(Map<String, dynamic> result) async {
    final token = result['token'] as String?;
    if (token == null) {
      throw const ApiException('The server did not return a session');
    }
    api.token = token;
    await _storage.write(key: _tokenKey, value: token);
    _apply(result);
    _set(AuthStatus.signedIn);
  }

  Future<void> signOut() async {
    try {
      await api.post('/api/auth/logout');
    } on ApiException {
      return _forget();
    }
    await _forget();
  }

  Future<void> refresh() async {
    if (!api.hasToken) return;
    try {
      _apply(await api.get('/api/me'));
      notifyListeners();
    } on ApiException {
      return;
    }
  }

  Future<void> updateSettings(Map<String, bool> changes) async {
    _apply(await api.patch('/api/me/settings', changes));
    notifyListeners();
  }

  Future<void> resetBrowser() async {
    _apply(await api.post('/api/me/browser/reset'));
    notifyListeners();
  }

  void _apply(Map<String, dynamic> me) {
    final user = me['user'];
    if (user is Map) _account = Account.fromJson(user.cast<String, dynamic>());
    final settings = me['settings'];
    if (settings is Map) {
      _settings = AgentSettings.fromJson(settings.cast<String, dynamic>());
    }
    final device = me['device'];
    if (device is Map) {
      _device = DeviceStatus.fromJson(device.cast<String, dynamic>());
    }
  }

  void _expired() {
    if (_status == AuthStatus.signedIn) _forget();
  }

  Future<void> _forget() async {
    api.token = null;
    _account = null;
    try {
      await _storage.delete(key: _tokenKey);
    } catch (_) {}
    _set(AuthStatus.signedOut);
  }

  void _set(AuthStatus status) {
    _status = status;
    notifyListeners();
  }
}

class AuthScope extends InheritedNotifier<AuthStore> {
  const AuthScope({super.key, required AuthStore auth, required super.child})
    : super(notifier: auth);

  static AuthStore of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AuthScope>();
    assert(scope != null, 'No AuthScope found in the widget tree.');
    return scope!.notifier!;
  }

  static AuthStore read(BuildContext context) {
    final scope = context.getInheritedWidgetOfExactType<AuthScope>();
    assert(scope != null, 'No AuthScope found in the widget tree.');
    return scope!.notifier!;
  }
}
