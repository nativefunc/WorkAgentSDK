import 'package:flutter/material.dart';

class AppInfo {
  AppInfo._();

  static const String name = 'OpenMuse';
}

class AppColors {
  AppColors._();

  static const Color canvas = Color(0xFFFFFFFF);

  static const Color surface = Color(0xFFF5F5F7);

  static const Color ink = Color(0xFF16161A);
  static const Color inkSecondary = Color(0xFF6B6B76);
  static const Color inkTertiary = Color(0xFF9D9DA8);

  static const Color bubble = Color(0xFFF2F2F5);

  static const Color accent = Color(0xFF5B5BF0);
  static const Color success = Color(0xFF2BB673);
  static const Color warning = Color(0xFFF2A93B);
  static const Color danger = Color(0xFFE5484D);

  static const Color hairline = Color(0x14000000);
}

class AppLayout {
  AppLayout._();

  static const double tabBarHeight = 56;
  static const double tabBarMaxWidth = 360;
  static const double pageGutter = 16;

  static const double readableWidth = 720;

  static const double listWidth = 640;

  static const double formWidth = 400;

  static const double sidebarBreakpoint = 900;
  static const double sidebarWidth = 320;

  static bool isWide(double width) => width >= sidebarBreakpoint;

  static double centeredInset(double available, double maxWidth) {
    final inset = (available - maxWidth) / 2;
    return inset > pageGutter ? inset : pageGutter;
  }

  static double tabBarBottomGap(BuildContext context) {
    final safeBottom = MediaQuery.paddingOf(context).bottom;
    final isAndroid = Theme.of(context).platform == TargetPlatform.android;
    if (isAndroid) return safeBottom + 10;
    return safeBottom > 12 ? safeBottom : 12;
  }

  static double contentBottomInset(BuildContext context) {
    return tabBarHeight + tabBarBottomGap(context) + 24;
  }
}

class AppTheme {
  AppTheme._();

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: AppColors.accent,
      brightness: Brightness.light,
    ).copyWith(surface: AppColors.canvas, onSurface: AppColors.ink);

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: AppColors.canvas,
      splashFactory: NoSplash.splashFactory,
      highlightColor: Colors.transparent,
      textSelectionTheme: const TextSelectionThemeData(
        cursorColor: AppColors.ink,
        selectionColor: Color(0x335B5BF0),
        selectionHandleColor: AppColors.ink,
      ),
      textTheme: const TextTheme(
        bodyMedium: TextStyle(color: AppColors.ink, fontSize: 15),
      ),
    );
  }
}
