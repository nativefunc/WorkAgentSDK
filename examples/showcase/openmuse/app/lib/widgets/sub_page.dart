import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../glass/glass_controls.dart';
import '../theme/app_theme.dart';
import '../utils/route_guard.dart';

Future<T?> pushSubPage<T>(BuildContext context, Widget page) {
  return singleFlight<T>(
    'page:${page.runtimeType}',
    () =>
        Navigator.of(context)
            .push<T>(CupertinoPageRoute<T>(builder: (_) => page)),
  );
}

class SubPage extends StatelessWidget {
  const SubPage({
    super.key,
    required this.title,
    required this.children,
    this.subtitle,
    this.trailing,
    this.overlay,
  });

  final String title;
  final String? subtitle;

  final Widget? trailing;

  final List<Widget> children;

  final Widget? overlay;

  @override
  Widget build(BuildContext context) {
    final padding = MediaQuery.paddingOf(context);
    final side = AppLayout.centeredInset(
      MediaQuery.sizeOf(context).width,
      AppLayout.listWidth,
    );

    return Scaffold(
      backgroundColor: AppColors.canvas,
      body: Stack(
        children: [
          ListView(
            padding: EdgeInsets.fromLTRB(
              side,
              padding.top + 72,
              side,
              padding.bottom + 32,
            ),
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 32,
                    fontWeight: FontWeight.w700,
                    letterSpacing: -0.8,
                    color: AppColors.ink,
                  ),
                ),
              ),
              if (subtitle != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 4, 4, 0),
                  child: Text(
                    subtitle!,
                    style: const TextStyle(
                      fontSize: 14.5,
                      height: 1.4,
                      color: AppColors.inkSecondary,
                    ),
                  ),
                ),
              ...children,
            ],
          ),

          Positioned(
            top: 0,
            left: 0,
            right: 0,
            height: padding.top + 64,
            child: IgnorePointer(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      AppColors.canvas,
                      AppColors.canvas.withValues(alpha: 0),
                    ],
                    stops: const [0.6, 1],
                  ),
                ),
              ),
            ),
          ),

          Positioned(
            top: padding.top + 6,
            left: 16,
            right: 16,
            child: Row(
              children: [
                GlassCircleButton(
                  icon: Icons.arrow_back_rounded,
                  semanticLabel: 'Back',
                  onTap: () => Navigator.of(context).maybePop(),
                ),
                const Spacer(),
                if (trailing != null) trailing!,
              ],
            ),
          ),

          if (overlay != null) Positioned.fill(child: overlay!),
        ],
      ),
    );
  }
}

class GroupedSection extends StatelessWidget {
  const GroupedSection({
    super.key,
    required this.children,
    this.title,
    this.footer,
    this.dividerInset = 52,
  });

  final String? title;
  final String? footer;
  final List<Widget> children;

  final double dividerInset;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var i = 0; i < children.length; i++) {
      if (i > 0) {
        rows.add(
          Padding(
            padding: EdgeInsets.only(left: dividerInset),
            child: const Divider(
              height: 0.5,
              thickness: 0.5,
              color: AppColors.hairline,
            ),
          ),
        );
      }
      rows.add(children[i]);
    }

    return Padding(
      padding: const EdgeInsets.only(top: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (title != null)
            Padding(
              padding: const EdgeInsets.only(left: 16, bottom: 8),
              child: Text(
                title!,
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.inkTertiary,
                ),
              ),
            ),
          ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: ColoredBox(
              color: AppColors.surface,
              child: Column(children: rows),
            ),
          ),
          if (footer != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Text(
                footer!,
                style: const TextStyle(
                  fontSize: 12.5,
                  height: 1.4,
                  color: AppColors.inkTertiary,
                ),
              ),
            ),
        ],
      ),
    );
  }
}
