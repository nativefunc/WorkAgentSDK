import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../../glass/glass_toast.dart';
import '../../state/auth_store.dart';
import '../../theme/app_theme.dart';
import '../../widgets/sub_page.dart';

class PermissionsPage extends StatefulWidget {
  const PermissionsPage({super.key});

  @override
  State<PermissionsPage> createState() => _PermissionsPageState();
}

class _PermissionsPageState extends State<PermissionsPage> {
  final Set<String> _saving = {};

  Future<void> _set(String key, bool value) async {
    setState(() => _saving.add(key));
    try {
      await AuthScope.read(context).updateSettings({key: value});
    } on ApiException catch (error) {
      if (mounted) {
        showGlassToast(
          context,
          error.message,
          icon: Icons.error_outline_rounded,
        );
      }
    } finally {
      if (mounted) setState(() => _saving.remove(key));
    }
  }

  @override
  Widget build(BuildContext context) {
    final settings = AuthScope.of(context).settings;

    Widget toggle(String key, bool value, String title, String detail) =>
        _ToggleRow(
          title: title,
          detail: detail,
          value: value,
          saving: _saving.contains(key),
          onChanged: (v) => _set(key, v),
        );

    return SubPage(
      title: 'Permissions',
      children: [
        GroupedSection(
          title: 'Allow',
          dividerInset: 16,
          children: [
            toggle(
              'computer',
              settings.computer,
              'Computer',
              'Use apps on the screen',
            ),
            toggle(
              'browser',
              settings.browser,
              'Browser',
              'Browse websites for you',
            ),
            toggle(
              'workspace',
              settings.workspace,
              'Workspace',
              'Work with files and run commands',
            ),
          ],
        ),
        GroupedSection(
          title: 'Ask me first',
          dividerInset: 16,
          children: [
            toggle(
              'confirm_submit',
              settings.confirmSubmit,
              'Before submitting a form',
              'Sign-ups, orders, messages',
            ),
            toggle(
              'confirm_shell',
              settings.confirmShell,
              'Before running a command',
              'In the workspace',
            ),
          ],
        ),
      ],
    );
  }
}

class _ToggleRow extends StatelessWidget {
  const _ToggleRow({
    required this.title,
    required this.detail,
    required this.value,
    required this.saving,
    required this.onChanged,
  });

  final String title;
  final String detail;
  final bool value;
  final bool saving;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 11, 12, 11),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                    color: AppColors.ink,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  detail,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.inkSecondary,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          SizedBox(
            height: 32,
            child: saving
                ? const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 16),
                    child: Center(
                      child: SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: AppColors.inkTertiary,
                        ),
                      ),
                    ),
                  )
                : CupertinoSwitch(
                    value: value,
                    activeTrackColor: AppColors.success,
                    onChanged: onChanged,
                  ),
          ),
        ],
      ),
    );
  }
}
