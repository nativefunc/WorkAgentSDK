import 'package:flutter/material.dart';

import 'glass_presets.dart';
import 'glass_surface.dart';
import '../utils/route_guard.dart';

Future<T?> showGlassSheet<T>(
  BuildContext context, {
  required WidgetBuilder builder,
}) {
  return singleFlight<T>('sheet', () => _showGlassSheet<T>(context, builder));
}

Future<T?> _showGlassSheet<T>(BuildContext context, WidgetBuilder builder) {
  return showModalBottomSheet<T>(
    context: context,
    useRootNavigator: true,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    barrierColor: const Color(0x1F000000),
    elevation: 0,
    builder: (sheetContext) {
      final media = MediaQuery.of(sheetContext);
      return Padding(
        padding: EdgeInsets.fromLTRB(
          10,
          0,
          10,
          media.viewInsets.bottom + media.padding.bottom + 10,
        ),
        child: GlassSurface(
          settings: GlassPresets.panel(),
          radius: 30,
          padding: const EdgeInsets.fromLTRB(20, 10, 20, 16),
          child: Column(
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
              Builder(builder: builder),
            ],
          ),
        ),
      );
    },
  );
}
