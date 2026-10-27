import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../../glass/glass_toast.dart';
import '../../glass/pressable.dart';
import '../../state/auth_store.dart';
import '../../theme/app_theme.dart';
import '../../widgets/sub_page.dart';
import 'device_page.dart';
import 'permissions_page.dart';
import '../../utils/route_guard.dart';

class ProfilePage extends StatelessWidget {
  const ProfilePage({super.key});

  Future<bool> _confirm(
    BuildContext context, {
    required String title,
    required String message,
    required String action,
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
              isDestructiveAction: true,
              onPressed: () => popRoute(dialogContext, true),
              child: Text(action),
            ),
          ],
        ),
      ),
    );
    return result == true;
  }

  Future<void> _clearCookies(BuildContext context) async {
    final ok = await _confirm(
      context,
      title: 'Clear cookies?',
      message: 'New chats will start with a browser that is signed out of every website.',
      action: 'Clear',
    );
    if (!ok || !context.mounted) return;
    try {
      await AuthScope.read(context).resetBrowser();
      if (context.mounted) {
        showGlassToast(context, 'Cookies cleared', icon: Icons.check_rounded);
      }
    } on ApiException catch (error) {
      if (context.mounted) {
        showGlassToast(
          context,
          error.message,
          icon: Icons.error_outline_rounded,
        );
      }
    }
  }

  Future<void> _logOut(BuildContext context) async {
    final ok = await _confirm(
      context,
      title: 'Log out?',
      message: 'You can sign back in at any time.',
      action: 'Log out',
    );
    if (ok && context.mounted) {
      await AuthScope.read(context).signOut();
    }
  }

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    final auth = AuthScope.of(context);
    final device = auth.device;
    final settings = auth.settings;
    final allowed = [
      if (settings.computer) 'Computer',
      if (settings.browser) 'Browser',
      if (settings.workspace) 'Workspace',
    ];
    final side = AppLayout.centeredInset(
      MediaQuery.sizeOf(context).width,
      AppLayout.listWidth,
    );

    return ListView(
      padding: EdgeInsets.fromLTRB(
        side,
        top + 40,
        side,
        AppLayout.contentBottomInset(context),
      ),
      children: [
        _Identity(account: auth.account),
        const SizedBox(height: 28),
        _Section(
          title: 'Your computer',
          footer: device.local
              ? 'The workspace, browser and screen the assistant uses run on its server.'
              : 'The workspace, browser and screen the assistant uses are all on your own computer.',
          rows: [
            _Row(
              icon: Icons.desktop_windows_outlined,
              title: 'Computer',
              value: !device.paired
                  ? 'Not connected'
                  : device.online
                  ? 'Online'
                  : 'Offline',
              onTap: () => pushSubPage<void>(context, const DevicePage()),
            ),
            _Row(
              icon: Icons.shield_outlined,
              title: 'Permissions',
              value: allowed.isEmpty ? 'All off' : '${allowed.length} of 3 on',
              onTap: () => pushSubPage<void>(context, const PermissionsPage()),
            ),
          ],
        ),
        _Section(
          title: 'Browser',
          footer: 'New chats start signed out of all websites.',
          rows: [
            _Row(
              icon: Icons.cookie_outlined,
              title: 'Clear cookies',
              showChevron: false,
              onTap: () => _clearCookies(context),
            ),
          ],
        ),
        _Section(
          rows: [
            _Row(
              title: 'Log out',
              destructive: true,
              centered: true,
              onTap: () => _logOut(context),
            ),
          ],
        ),
      ],
    );
  }
}

class _Identity extends StatelessWidget {
  const _Identity({required this.account});

  final Account? account;

  @override
  Widget build(BuildContext context) {
    final account = this.account;
    return Column(
      children: [
        CircleAvatar(
          radius: 42,
          backgroundColor: const Color(0xFF5BBF9A),
          child: Text(
            account?.initials ?? '?',
            style: const TextStyle(
              fontSize: 27,
              fontWeight: FontWeight.w700,
              color: Colors.white,
            ),
          ),
        ),
        const SizedBox(height: 12),
        Text(
          account?.name ?? '',
          style: const TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.w700,
            color: AppColors.ink,
          ),
        ),
        if (account != null)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(
              account.email,
              style: const TextStyle(
                fontSize: 14,
                color: AppColors.inkSecondary,
              ),
            ),
          ),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.rows, this.title, this.footer});

  final String? title;
  final String? footer;
  final List<_Row> rows;

  @override
  Widget build(BuildContext context) {
    final children = <Widget>[];
    for (var i = 0; i < rows.length; i++) {
      if (i > 0) {
        children.add(
          Padding(
            padding: EdgeInsets.only(left: rows[i].icon == null ? 16 : 52),
            child: const Divider(
              height: 0.5,
              thickness: 0.5,
              color: AppColors.hairline,
            ),
          ),
        );
      }
      children.add(rows[i]);
    }

    return Padding(
      padding: const EdgeInsets.only(top: 22),
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
              child: Column(children: children),
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

class _Row extends StatelessWidget {
  const _Row({
    required this.title,
    required this.onTap,
    this.icon,
    this.value,
    this.destructive = false,
    this.centered = false,
    this.showChevron = true,
  });

  final IconData? icon;
  final String title;
  final String? value;
  final VoidCallback onTap;
  final bool destructive;
  final bool centered;
  final bool showChevron;

  @override
  Widget build(BuildContext context) {
    final color = destructive ? AppColors.danger : AppColors.ink;
    final label = Text(
      title,
      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500, color: color),
    );

    return Pressable(
      onTap: onTap,
      semanticLabel: title,
      pressedScale: 0.98,
      haptics: false,
      child: SizedBox(
        height: 52,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: centered
              ? Center(child: label)
              : Row(
                  children: [
                    if (icon != null) ...[
                      Icon(icon, size: 22, color: color),
                      const SizedBox(width: 14),
                    ],
                    Expanded(child: label),
                    if (value != null)
                      Padding(
                        padding: const EdgeInsets.only(right: 4),
                        child: Text(
                          value!,
                          style: const TextStyle(
                            fontSize: 15,
                            color: AppColors.inkTertiary,
                          ),
                        ),
                      ),
                    if (showChevron && !destructive)
                      const Icon(
                        Icons.chevron_right_rounded,
                        size: 22,
                        color: AppColors.inkTertiary,
                      ),
                  ],
                ),
        ),
      ),
    );
  }
}
