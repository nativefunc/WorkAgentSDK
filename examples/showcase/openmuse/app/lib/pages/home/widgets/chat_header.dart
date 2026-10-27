import 'package:flutter/material.dart';

import '../../../glass/glass_controls.dart';
import '../../../glass/glass_presets.dart';
import '../../../glass/glass_surface.dart';
import '../../../glass/pressable.dart';
import '../../../state/cloud_connections.dart';
import '../../../theme/app_theme.dart';

class ChatHeader extends StatelessWidget {
  const ChatHeader({
    super.key,
    required this.cloud,
    required this.onMenu,
    this.menuIcon = Icons.notes_rounded,
    required this.onConnections,
    required this.onNewChat,
  });

  final CloudConnections cloud;
  final VoidCallback onMenu;

  final IconData menuIcon;
  final VoidCallback onConnections;
  final VoidCallback onNewChat;

  static const double height = 58;

  static const double _capsuleHeight = 48;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      bottom: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
        child: SizedBox(
          height: _capsuleHeight,
          child: Row(
            children: [
              GlassCircleButton(
                icon: menuIcon,
                semanticLabel: 'Chats',
                size: _capsuleHeight,
                onTap: onMenu,
              ),
              const Spacer(),
              GlassSurface(
                settings: GlassPresets.control,
                radius: _capsuleHeight / 2,
                height: _capsuleHeight,
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    ListenableBuilder(
                      listenable: cloud.listenable,
                      builder: (context, _) => _CapsuleButton(
                        icon: Icons.desktop_windows_outlined,
                        semanticLabel: 'Cloud connections',
                        onTap: onConnections,
                        badge: _StatusDot(state: cloud.overall),
                      ),
                    ),
                    _CapsuleButton(
                      icon: Icons.edit_outlined,
                      semanticLabel: 'New chat',
                      onTap: onNewChat,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CapsuleButton extends StatelessWidget {
  const _CapsuleButton({
    required this.icon,
    required this.semanticLabel,
    required this.onTap,
    this.badge,
  });

  final IconData icon;
  final String semanticLabel;
  final VoidCallback onTap;
  final Widget? badge;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: semanticLabel,
      pressedScale: 0.88,
      child: SizedBox(
        width: 44,
        height: 40,
        child: Stack(
          clipBehavior: Clip.none,
          alignment: Alignment.center,
          children: [
            Icon(icon, size: 23, color: AppColors.ink),
            if (badge != null) Positioned(top: 7, right: 7, child: badge!),
          ],
        ),
      ),
    );
  }
}

class _StatusDot extends StatefulWidget {
  const _StatusDot({required this.state});

  final CloudState state;

  @override
  State<_StatusDot> createState() => _StatusDotState();
}

class _StatusDotState extends State<_StatusDot>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 800),
  );

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(_StatusDot oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state) _sync();
  }

  void _sync() {
    if (widget.state == CloudState.connecting) {
      _pulse.repeat(reverse: true);
    } else {
      _pulse
        ..stop()
        ..value = 1;
    }
  }

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.state == CloudState.disconnected) {
      return const SizedBox.shrink();
    }
    final color = widget.state == CloudState.connected
        ? AppColors.success
        : AppColors.warning;
    return FadeTransition(
      opacity: Tween<double>(begin: 0.35, end: 1).animate(_pulse),
      child: Container(
        width: 9,
        height: 9,
        decoration: BoxDecoration(
          color: color,
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 1.5),
        ),
      ),
    );
  }
}
