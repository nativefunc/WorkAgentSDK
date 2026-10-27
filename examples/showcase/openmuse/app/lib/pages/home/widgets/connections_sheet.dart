import 'package:flutter/material.dart';

import '../../../glass/glass_presets.dart';
import '../../../glass/glass_surface.dart';
import '../../../glass/pressable.dart';
import '../../../state/cloud_connections.dart';
import '../../../theme/app_theme.dart';
import '../../../widgets/sub_page.dart';
import '../../profile/device_page.dart';
import '../../remote/take_control_page.dart';
import '../../../utils/route_guard.dart';

Future<void> showConnectionsSheet(
  BuildContext context,
  CloudConnections cloud, {
  String? chatId,
}) async {
  await singleFlight<void>(
    'connections',
    () => showModalBottomSheet<void>(
      context: context,
      useRootNavigator: true,
      backgroundColor: Colors.transparent,
      barrierColor: const Color(0x1F000000),
      elevation: 0,
      builder: (sheetContext) =>
          _ConnectionsSheet(cloud: cloud, chatId: chatId),
    ),
  );
}

({IconData icon, String title, String subtitle}) kindInfo(CloudKind kind) =>
    switch (kind) {
      CloudKind.computer => (
        icon: Icons.desktop_windows_outlined,
        title: 'Computer',
        subtitle: 'Apps on your screen, one at a time with your OK',
      ),
      CloudKind.browser => (
        icon: Icons.public_rounded,
        title: 'Browser',
        subtitle: 'Public websites; you sign in yourself',
      ),
      CloudKind.workspace => (
        icon: Icons.folder_outlined,
        title: 'Workspace',
        subtitle: 'One folder, sandboxed commands',
      ),
    };

class _ConnectionsSheet extends StatelessWidget {
  const _ConnectionsSheet({required this.cloud, this.chatId});

  final CloudConnections cloud;
  final String? chatId;

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.paddingOf(context).bottom;

    return Padding(
      padding: EdgeInsets.fromLTRB(10, 0, 10, bottom + 10),
      child: GlassSurface(
        settings: GlassPresets.panel(),
        radius: 30,
        padding: const EdgeInsets.fromLTRB(20, 10, 20, 12),
        child: ListenableBuilder(
          listenable: Listenable.merge([cloud.listenable, cloud.auth]),
          builder: (context, _) => Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 36,
                  height: 5,
                  margin: const EdgeInsets.only(bottom: 14),
                  decoration: BoxDecoration(
                    color: const Color(0x26000000),
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
              ),
              const Text(
                'Connections',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  color: AppColors.ink,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                !cloud.paired
                    ? 'Connect your computer so the assistant can work on it.'
                    : cloud.online
                    ? 'What the assistant may use on your computer.'
                    : 'Your computer is offline. Start OpenMuse on it to continue.',
                style: const TextStyle(
                  fontSize: 14,
                  height: 1.35,
                  color: AppColors.inkSecondary,
                ),
              ),
              if (!cloud.paired || !cloud.online)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: _Pill(
                    label: cloud.paired
                        ? 'How to start it'
                        : 'Connect your computer',
                    icon: Icons.link_rounded,
                    dark: true,
                    onTap: () {
                      if (!isTopRoute(context)) return;
                      final navigator = Navigator.of(
                        context,
                        rootNavigator: true,
                      );
                      navigator.pop();
                      pushSubPage<void>(navigator.context, const DevicePage());
                    },
                  ),
                ),
              if (cloud.error.value != null)
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: Text(
                    cloud.error.value!,
                    style: const TextStyle(
                      fontSize: 13,
                      color: AppColors.danger,
                    ),
                  ),
                ),
              const SizedBox(height: 8),
              for (var i = 0; i < cloud.all.length; i++) ...[
                if (i > 0)
                  const Divider(
                    height: 1,
                    thickness: 0.5,
                    color: AppColors.hairline,
                  ),
                _ConnectionRow(connection: cloud.all[i], chatId: chatId),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ConnectionRow extends StatelessWidget {
  const _ConnectionRow({required this.connection, this.chatId});

  final CloudConnection connection;
  final String? chatId;

  @override
  Widget build(BuildContext context) {
    final info = kindInfo(connection.kind);
    final state = connection.value;

    final (statusText, statusColor) = switch (state) {
      CloudState.connected => ('On · ${info.subtitle}', AppColors.success),
      CloudState.connecting => ('Saving…', AppColors.warning),
      CloudState.offline => ('On · computer offline', AppColors.warning),
      CloudState.disconnected => (
        'Off · the assistant cannot use it',
        AppColors.inkTertiary,
      ),
    };

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(info.icon, size: 24, color: AppColors.ink),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      info.title,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        Container(
                          width: 7,
                          height: 7,
                          decoration: BoxDecoration(
                            color: statusColor,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 6),
                        Flexible(
                          child: Text(
                            statusText,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 13.5,
                              color: AppColors.inkSecondary,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              _ActionButton(connection: connection),
            ],
          ),
          if (connection.kind.canTakeControl && state == CloudState.connected)
            Padding(
              padding: const EdgeInsets.only(left: 38, top: 12),
              child: _Pill(
                label: 'Take control',
                icon: Icons.back_hand_outlined,
                onTap: () {
                  if (!isTopRoute(context)) return;
                  final navigator = Navigator.of(context, rootNavigator: true);
                  navigator.pop();
                  showTakeControl(
                    navigator.context,
                    connection,
                    chatId: chatId,
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({
    required this.label,
    required this.icon,
    required this.onTap,
    this.dark = false,
  });

  final String label;
  final IconData icon;
  final VoidCallback onTap;
  final bool dark;

  @override
  Widget build(BuildContext context) {
    final color = dark ? Colors.white : AppColors.ink;
    return Align(
      alignment: Alignment.centerLeft,
      child: Pressable(
        semanticLabel: label,
        onTap: onTap,
        child: Container(
          height: 40,
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: ShapeDecoration(
            color: dark ? AppColors.ink : AppColors.surface,
            shape: const StadiumBorder(),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 18, color: color),
              const SizedBox(width: 8),
              Text(
                label,
                style: TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w600,
                  color: color,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({required this.connection});

  final CloudConnection connection;

  @override
  Widget build(BuildContext context) {
    switch (connection.value) {
      case CloudState.connecting:
        return const SizedBox(
          width: 20,
          height: 20,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: AppColors.inkTertiary,
          ),
        );
      case CloudState.connected:
      case CloudState.offline:
        return _pill('Turn off', dark: false, onTap: connection.disconnect);
      case CloudState.disconnected:
        return _pill('Turn on', dark: true, onTap: connection.connect);
    }
  }

  Widget _pill(
    String label, {
    required bool dark,
    required VoidCallback onTap,
  }) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.94,
      child: Container(
        height: 34,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        alignment: Alignment.center,
        decoration: ShapeDecoration(
          color: dark ? AppColors.ink : AppColors.surface,
          shape: const StadiumBorder(),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: dark ? Colors.white : AppColors.ink,
          ),
        ),
      ),
    );
  }
}
