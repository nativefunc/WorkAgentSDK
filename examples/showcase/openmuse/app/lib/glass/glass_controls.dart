import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'glass_presets.dart';
import 'glass_settings.dart';
import 'glass_surface.dart';
import 'pressable.dart';

class GlassCircleButton extends StatelessWidget {
  const GlassCircleButton({
    super.key,
    required this.icon,
    required this.onTap,
    required this.semanticLabel,
    this.size = 44,
    this.iconSize = 22,
    this.iconColor = AppColors.ink,
    this.showBadge = false,
    this.settings = GlassPresets.control,
  });

  final IconData icon;
  final VoidCallback? onTap;
  final String semanticLabel;
  final double size;
  final double iconSize;
  final Color iconColor;
  final bool showBadge;

  final GlassSettings settings;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: semanticLabel,
      pressedScale: 0.9,
      child: SizedBox.square(
        dimension: size,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Positioned.fill(
              child: GlassSurface(
                circle: true,
                settings: settings,
                width: size,
                height: size,
                child: Center(
                  child: Icon(icon, size: iconSize, color: iconColor),
                ),
              ),
            ),
            if (showBadge)
              Positioned(
                top: size * 0.12,
                right: size * 0.12,
                child: Container(
                  width: 9,
                  height: 9,
                  decoration: BoxDecoration(
                    color: AppColors.accent,
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white, width: 1.5),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class GlassPill extends StatelessWidget {
  const GlassPill({
    super.key,
    required this.label,
    this.leading,
    this.onTap,
    this.height = 32,
    this.horizontalPadding = 14,
    this.fontSize = 14,
  });

  final String label;
  final Widget? leading;
  final VoidCallback? onTap;
  final double height;
  final double horizontalPadding;
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final pill = GlassSurface(
      settings: GlassPresets.control,
      radius: height / 2,
      height: height,
      shadow: false,
      padding: EdgeInsets.symmetric(horizontal: horizontalPadding),
      child: Center(
        widthFactor: 1,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (leading != null) ...[leading!, const SizedBox(width: 6)],
            Text(
              label,
              maxLines: 1,
              style: TextStyle(
                fontSize: fontSize,
                fontWeight: FontWeight.w600,
                color: AppColors.ink,
                letterSpacing: -0.1,
              ),
            ),
          ],
        ),
      ),
    );

    if (onTap == null) return pill;
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.95,
      child: pill,
    );
  }
}
