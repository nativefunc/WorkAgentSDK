import 'dart:async';

import 'package:flutter/material.dart';

import 'pages/auth/login_page.dart';
import 'pages/root_shell.dart';
import 'state/activity_store.dart';
import 'state/app_events.dart';
import 'state/auth_store.dart';
import 'state/chat_store.dart';
import 'state/navigation.dart';
import 'theme/app_theme.dart';

class OpenMuseApp extends StatefulWidget {
  const OpenMuseApp({super.key, this.serverUrl});

  final String? serverUrl;

  @override
  State<OpenMuseApp> createState() => _OpenMuseAppState();
}

class _OpenMuseAppState extends State<OpenMuseApp> with WidgetsBindingObserver {
  late final AuthStore _auth = AuthStore(serverUrl: widget.serverUrl);
  late final ChatStore _store = ChatStore(auth: _auth);
  late final ActivityStore _activity = ActivityStore(auth: _auth);
  late final ShellNavigation _navigation = ShellNavigation();
  late final AppEvents _events = AppEvents(
    auth: _auth,
    chats: _store,
    activity: _activity,
  );

  AuthStatus? _lastStatus;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _auth.addListener(_onAuth);
    unawaited(_auth.restore());
  }

  void _onAuth() {
    final status = _auth.status;
    if (status == _lastStatus) return;
    _lastStatus = status;
    if (status == AuthStatus.signedIn) {
      unawaited(_store.start());
      unawaited(_activity.refresh());
      _events.start();
    } else if (status == AuthStatus.signedOut) {
      _events.stop();
      _store.reset();
      _activity.reset();
      _navigation.go(ShellNavigation.home);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!_auth.isSignedIn) return;
    if (state == AppLifecycleState.resumed) {
      unawaited(_store.start());
      unawaited(_activity.refresh());
      unawaited(_auth.refresh());
      _events.start();
    } else if (state == AppLifecycleState.paused) {
      _events.stop();
      _store.pause();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _auth.removeListener(_onAuth);
    _events.stop();
    _store.dispose();
    _activity.dispose();
    _navigation.dispose();
    _auth.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AuthScope(
      auth: _auth,
      child: ChatScope(
        store: _store,
        child: ActivityScope(
          activity: _activity,
          child: ShellScope(
            navigation: _navigation,
            child: MaterialApp(
              title: AppInfo.name,
              debugShowCheckedModeBanner: false,
              theme: AppTheme.light(),
              home: const _AuthGate(),
            ),
          ),
        ),
      ),
    );
  }
}

class _AuthGate extends StatelessWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context) {
    final status = AuthScope.of(context).status;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 350),
      child: switch (status) {
        AuthStatus.restoring => const _Splash(key: ValueKey('splash')),
        AuthStatus.signedIn => const RootShell(key: ValueKey('app')),
        AuthStatus.signedOut => const LoginPage(key: ValueKey('login')),
      },
    );
  }
}

class _Splash extends StatelessWidget {
  const _Splash({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.canvas,
      body: Center(
        child: Text(
          AppInfo.name,
          style: TextStyle(
            fontSize: 34,
            fontWeight: FontWeight.w700,
            letterSpacing: -0.8,
            color: AppColors.ink,
          ),
        ),
      ),
    );
  }
}
