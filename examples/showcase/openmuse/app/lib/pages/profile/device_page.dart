import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/api_client.dart';
import '../../glass/glass_toast.dart';
import '../../glass/pressable.dart';
import '../../state/auth_store.dart';
import '../../theme/app_theme.dart';
import '../../widgets/sub_page.dart';
import '../../utils/route_guard.dart';

class DevicePage extends StatefulWidget {
  const DevicePage({super.key});

  @override
  State<DevicePage> createState() => _DevicePageState();
}

class _DevicePageState extends State<DevicePage> {
  Map<String, dynamic>? _status;

  Map<String, dynamic>? _pairing;
  bool _busy = false;
  Timer? _poll;
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 4), (_) => _load());
  }

  @override
  void dispose() {
    _poll?.cancel();
    _tick?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final auth = AuthScope.read(context);
    try {
      final status = await auth.api.get('/api/device');
      if (!mounted) return;
      final wasOnline = _online;
      setState(() => _status = status);
      if (_online != wasOnline) unawaited(auth.refresh());
      final pairing = _pairing;
      final pairedAt = (status['paired_at'] as num?)?.toDouble() ?? 0;
      final issuedAt = (pairing?['issued_at'] as num?)?.toDouble() ?? 0;
      if (pairing != null && pairedAt >= issuedAt && issuedAt > 0) {
        _endPairing();
        unawaited(auth.refresh());
        showGlassToast(
          context,
          'Computer connected',
          icon: Icons.check_rounded,
        );
      }
    } on ApiException {
      return;
    }
  }

  bool get _online => _status?['online'] == true;
  bool get _paired => _status?['paired'] == true;

  bool get _local => _status?['mode'] == 'local';
  Map<String, dynamic> get _info =>
      (_status?['info'] as Map?)?.cast<String, dynamic>() ?? const {};

  Future<void> _pair() async {
    if (_paired) {
      final ok = await _confirm(
        title: 'Connect a different computer?',
        message: 'Once the new computer is connected, the current one is disconnected.',
        action: 'Continue',
      );
      if (!ok || !mounted) return;
    }
    setState(() => _busy = true);
    try {
      final result = await AuthScope.read(context).api.post('/api/device/code');
      if (!mounted) return;
      final ttl = ((result['expires_at'] as num) - (result['issued_at'] as num))
          .toDouble();
      setState(
        () => _pairing = {
          ...result,
          'local_expires_at':
              DateTime.now().millisecondsSinceEpoch / 1000 + ttl,
        },
      );
      _tick?.cancel();
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!mounted) return;
        if (_secondsLeft <= 0) {
          _endPairing();
        } else {
          setState(() {});
        }
      });
    } on ApiException catch (error) {
      if (mounted) {
        showGlassToast(
          context,
          error.message,
          icon: Icons.error_outline_rounded,
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _endPairing() {
    _tick?.cancel();
    _tick = null;
    if (mounted) setState(() => _pairing = null);
  }

  int get _secondsLeft {
    final expires = (_pairing?['local_expires_at'] as num?)?.toDouble() ?? 0;
    return (expires - DateTime.now().millisecondsSinceEpoch / 1000).floor();
  }

  Future<void> _unpair() async {
    final ok = await _confirm(
      title: 'Disconnect this computer?',
      message: 'The assistant loses access to its workspace, browser and screen until you connect it again.',
      action: 'Disconnect',
      destructive: true,
    );
    if (!ok || !mounted) return;
    final auth = AuthScope.read(context);
    try {
      await auth.api.delete('/api/device');
      if (!mounted) return;
      _endPairing();
      await _load();
      await auth.refresh();
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

  Future<bool> _confirm({
    required String title,
    required String message,
    required String action,
    bool destructive = false,
  }) async {
    final result = await singleFlight<bool>(
      'confirm',
      () => showCupertinoDialog<bool>(
        context: context,
        builder: (dialogContext) => CupertinoAlertDialog(
          title: Text(title),
          content: Text(message),
          actions: [
            CupertinoDialogAction(
              onPressed: () => popRoute(dialogContext, false),
              child: const Text('Cancel'),
            ),
            CupertinoDialogAction(
              isDestructiveAction: destructive,
              onPressed: () => popRoute(dialogContext, true),
              child: Text(action),
            ),
          ],
        ),
      ),
    );
    return result == true;
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    final info = _info;
    final pairing = _pairing;

    final String headline;
    final String detail;
    final Color dot;
    if (status == null) {
      headline = 'Checking…';
      detail = '';
      dot = AppColors.inkTertiary;
    } else if (!_paired) {
      headline = 'Not connected';
      detail =
          'Connect a computer so ${AppInfo.name} can browse, use apps and work with files for you.';
      dot = AppColors.inkTertiary;
    } else if (_online) {
      headline = info['paused'] == true ? 'Paused on the computer' : 'Online';
      detail = [
        if (info['os'] != null) _osName(info['os'] as String),
        if (info['screen'] == true) 'screen',
        if (info['browser'] == true) 'browser',
        'workspace',
      ].join(' · ');
      dot = info['paused'] == true ? AppColors.warning : AppColors.success;
    } else {
      headline = 'Offline';
      detail = 'Start OpenMuse on the computer to bring it online.';
      dot = AppColors.warning;
    }

    return SubPage(
      title: 'Your computer',
      subtitle: _local
          ? 'The workspace, browser and screen ${AppInfo.name} uses run on its server.'
          : 'The workspace, browser and screen ${AppInfo.name} uses all live here.',
      children: [
        GroupedSection(
          dividerInset: 16,
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.desktop_windows_outlined,
                    size: 30,
                    color: AppColors.ink,
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Container(
                              width: 8,
                              height: 8,
                              decoration: BoxDecoration(
                                color: dot,
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: 7),
                            Text(
                              headline,
                              style: const TextStyle(
                                fontSize: 17,
                                fontWeight: FontWeight.w600,
                                color: AppColors.ink,
                              ),
                            ),
                          ],
                        ),
                        if (detail.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              detail,
                              style: const TextStyle(
                                fontSize: 14,
                                height: 1.4,
                                color: AppColors.inkSecondary,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        if (!_local && pairing != null)
          _PairingCode(
            code: pairing['code'] as String? ?? '',
            command: pairing['command'] as String? ?? '',
            secondsLeft: _secondsLeft,
            onCancel: _endPairing,
          )
        else if (!_local) ...[
          const SizedBox(height: 18),
          Pressable(
            onTap: _busy ? null : _pair,
            semanticLabel: _paired
                ? 'Connect a different computer'
                : 'Connect a computer',
            pressedScale: 0.97,
            child: Container(
              height: 52,
              alignment: Alignment.center,
              decoration: ShapeDecoration(
                color: _paired ? AppColors.surface : AppColors.ink,
                shape: const StadiumBorder(),
              ),
              child: _busy
                  ? SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.2,
                        color: _paired ? AppColors.ink : Colors.white,
                      ),
                    )
                  : Text(
                      _paired
                          ? 'Connect a different computer'
                          : 'Connect a computer',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: _paired ? AppColors.ink : Colors.white,
                      ),
                    ),
            ),
          ),
        ],
        if (_paired && !_local && pairing == null)
          GroupedSection(
            children: [
              Pressable(
                onTap: _unpair,
                semanticLabel: 'Disconnect this computer',
                pressedScale: 0.98,
                haptics: false,
                child: const SizedBox(
                  height: 52,
                  child: Center(
                    child: Text(
                      'Disconnect this computer',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w500,
                        color: AppColors.danger,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
      ],
    );
  }

  static String _osName(String os) => switch (os) {
    'macos' || 'darwin' => 'macOS',
    'linux' => 'Linux',
    'windows' => 'Windows',
    _ => os,
  };
}

class _PairingCode extends StatelessWidget {
  const _PairingCode({
    required this.code,
    required this.command,
    required this.secondsLeft,
    required this.onCancel,
  });

  final String code;
  final String command;
  final int secondsLeft;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final spaced = code.length == 6
        ? '${code.substring(0, 3)} ${code.substring(3)}'
        : code;
    final left = secondsLeft.clamp(0, 3600);
    final clock = '${left ~/ 60}:${(left % 60).toString().padLeft(2, '0')}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        GroupedSection(
          title: 'Pairing code',
          footer: 'Expires in $clock',
          children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 22),
              child: Text(
                spaced,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 40,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 4,
                  color: AppColors.ink,
                  fontFeatures: [FontFeature.tabularFigures()],
                ),
              ),
            ),
          ],
        ),
        GroupedSection(
          title: 'On the computer, run',
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
              child: Row(
                children: [
                  Expanded(
                    child: SelectableText(
                      command,
                      style: const TextStyle(
                        fontSize: 12.5,
                        height: 1.45,
                        fontFamily: 'monospace',
                        color: AppColors.ink,
                      ),
                    ),
                  ),
                  Pressable(
                    onTap: () async {
                      await Clipboard.setData(ClipboardData(text: command));
                      if (context.mounted) {
                        showGlassToast(
                          context,
                          'Copied',
                          icon: Icons.copy_rounded,
                        );
                      }
                    },
                    semanticLabel: 'Copy command',
                    pressedScale: 0.88,
                    child: const SizedBox.square(
                      dimension: 36,
                      child: Icon(
                        Icons.copy_rounded,
                        size: 19,
                        color: AppColors.inkSecondary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        Center(
          child: Pressable(
            onTap: onCancel,
            semanticLabel: 'Cancel',
            pressedScale: 0.96,
            haptics: false,
            child: const Padding(
              padding: EdgeInsets.all(12),
              child: Text(
                'Cancel',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w500,
                  color: AppColors.inkSecondary,
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
