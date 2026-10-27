import 'package:flutter/material.dart';

import '../../../glass/glass_sheet.dart';
import '../../../glass/pressable.dart';
import '../../../theme/app_theme.dart';
import '../../../utils/route_guard.dart';

enum AttachSource { photos, files }

Future<AttachSource?> showAttachSheet(BuildContext context) {
  return showGlassSheet<AttachSource>(
    context,
    builder: (sheetContext) => Row(
      children: [
        Expanded(
          child: _Tile(
            icon: Icons.photo_library_outlined,
            label: 'Photos',
            onTap: () => popRoute(sheetContext, AttachSource.photos),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _Tile(
            icon: Icons.folder_outlined,
            label: 'Files',
            onTap: () => popRoute(sheetContext, AttachSource.files),
          ),
        ),
      ],
    ),
  );
}

class _Tile extends StatelessWidget {
  const _Tile({required this.icon, required this.label, required this.onTap});

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.96,
      child: Container(
        height: 96,
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(22),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 26, color: AppColors.ink),
            const SizedBox(height: 8),
            Text(
              label,
              style: const TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: AppColors.ink,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
