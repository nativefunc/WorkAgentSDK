import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'glass_presets.dart';
import 'glass_surface.dart';

OverlayEntry? _activeToast;

void showGlassToast(BuildContext context, String message, {IconData? icon}) {
  final overlay = Overlay.maybeOf(context, rootOverlay: true);
  if (overlay == null) return;

  _dismissActiveToast();

  final key = UniqueKey();
  late final OverlayEntry entry;
  entry = OverlayEntry(
    builder: (context) => _GlassToast(
      key: key,
      message: message,
      icon: icon,
      onFinished: () {
        if (_activeToast == entry) _activeToast = null;
        if (entry.mounted) entry.remove();
      },
    ),
  );
  _activeToast = entry;
  overlay.insert(entry);
}

void _dismissActiveToast() {
  final current = _activeToast;
  _activeToast = null;
  if (current != null && current.mounted) current.remove();
}

class _GlassToast extends StatefulWidget {
  const _GlassToast({
    super.key,
    required this.message,
    required this.onFinished,
    this.icon,
  });

  final String message;
  final IconData? icon;
  final VoidCallback onFinished;

  @override
  State<_GlassToast> createState() => _GlassToastState();
}

class _GlassToastState extends State<_GlassToast>
    with SingleTickerProviderStateMixin {
  static const double _height = 44;

  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 300),
    reverseDuration: const Duration(milliseconds: 200),
  );

  @override
  void initState() {
    super.initState();
    _run();
  }

  Future<void> _run() async {
    try {
      await _controller.forward().orCancel;
      await Future<void>.delayed(const Duration(milliseconds: 1500));
      if (!mounted) return;
      await _controller.reverse().orCancel;
    } on TickerCanceled {
      return;
    }
    if (mounted) widget.onFinished();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top + 8;

    return Positioned(
      top: top,
      left: 24,
      right: 24,
      child: IgnorePointer(
        child: Material(
          type: MaterialType.transparency,
          child: Center(
            child: AnimatedBuilder(
              animation: _controller,
              builder: (context, _) {
                final t = Curves.easeOutCubic.transform(_controller.value);
                return Transform.translate(
                  offset: Offset(0, -12 * (1 - t)),
                  child: Transform.scale(
                    scale: 0.92 + 0.08 * t,
                    child: GlassSurface(
                      settings: GlassPresets.panel(visibility: t),
                      strength: t,
                      radius: _height / 2,
                      height: _height,
                      padding: const EdgeInsets.symmetric(horizontal: 18),
                      child: Opacity(
                        opacity: t,
                        child: Center(
                          widthFactor: 1,
                          child: _ToastContent(
                            message: widget.message,
                            icon: widget.icon,
                          ),
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}

class _ToastContent extends StatelessWidget {
  const _ToastContent({required this.message, this.icon});

  final String message;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (icon != null) ...[
          Icon(icon, size: 18, color: AppColors.ink),
          const SizedBox(width: 8),
        ],
        Flexible(
          child: Text(
            message,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.ink,
              decoration: TextDecoration.none,
            ),
          ),
        ),
      ],
    );
  }
}
