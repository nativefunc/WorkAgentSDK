import 'dart:convert';

import 'package:flutter/material.dart';

import '../../../glass/pressable.dart';
import '../../../models/chat_models.dart';
import '../../../theme/app_theme.dart';

class RequestCard extends StatelessWidget {
  const RequestCard({
    super.key,
    required this.request,
    required this.columnWidth,
    required this.busy,
    required this.onAnswer,
    required this.onTakeOver,
  });

  final ChatRequest request;
  final double columnWidth;

  final bool busy;
  final ValueChanged<Object?> onAnswer;
  final ValueChanged<ChatRequest> onTakeOver;

  @override
  Widget build(BuildContext context) {
    final Widget body = switch (request.type) {
      'AskUser' => _AskUser(request: request, busy: busy, onAnswer: onAnswer),
      'Approval' => _Approval(request: request, busy: busy, onAnswer: onAnswer),
      'AppAccess' => _AppAccess(
        request: request,
        busy: busy,
        onAnswer: onAnswer,
      ),
      'Takeover' => _Takeover(
        request: request,
        busy: busy,
        onDone: () => onAnswer(const {'done': true}),
        onTakeOver: () => onTakeOver(request),
      ),
      _ => _Unknown(request: request),
    };

    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Container(
          constraints: BoxConstraints(maxWidth: columnWidth * 0.92),
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
          decoration: BoxDecoration(
            color: AppColors.canvas,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: const Color(0x1A000000)),
            boxShadow: const [
              BoxShadow(
                color: Color(0x0F000000),
                blurRadius: 18,
                offset: Offset(0, 6),
              ),
            ],
          ),
          child: body,
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Icon(icon, size: 16, color: AppColors.inkTertiary),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w600,
              color: AppColors.inkTertiary,
              letterSpacing: 0.2,
            ),
          ),
        ],
      ),
    );
  }
}

class _Title extends StatelessWidget {
  const _Title(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 16,
        height: 1.35,
        fontWeight: FontWeight.w600,
        color: AppColors.ink,
      ),
    );
  }
}

class CardButton extends StatelessWidget {
  const CardButton({
    super.key,
    required this.label,
    required this.onTap,
    this.dark = false,
    this.busy = false,
    this.icon,
  });

  final String label;
  final VoidCallback? onTap;
  final bool dark;
  final bool busy;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final color = dark ? Colors.white : AppColors.ink;
    return Pressable(
      onTap: busy ? null : onTap,
      semanticLabel: label,
      pressedScale: 0.95,
      child: Container(
        height: 40,
        padding: const EdgeInsets.symmetric(horizontal: 18),
        decoration: ShapeDecoration(
          color: dark ? AppColors.ink : AppColors.surface,
          shape: const StadiumBorder(),
        ),
        child: Center(
          widthFactor: 1,
          child: busy
              ? SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: color,
                  ),
                )
              : Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (icon != null) ...[
                      Icon(icon, size: 17, color: color),
                      const SizedBox(width: 6),
                    ],
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

class _Buttons extends StatelessWidget {
  const _Buttons({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        alignment: WrapAlignment.end,
        children: children,
      ),
    );
  }
}

class _AskUser extends StatefulWidget {
  const _AskUser({
    required this.request,
    required this.busy,
    required this.onAnswer,
  });

  final ChatRequest request;
  final bool busy;
  final ValueChanged<Object?> onAnswer;

  @override
  State<_AskUser> createState() => _AskUserState();
}

class _AskUserState extends State<_AskUser> {
  final Set<String> _selected = {};
  final TextEditingController _other = TextEditingController();
  bool _otherOpen = false;

  @override
  void dispose() {
    _other.dispose();
    super.dispose();
  }

  bool get _multi => widget.request.data['multi_select'] == true;

  List<({String label, String description})> get _options => [
    for (final option in (widget.request.data['options'] as List?) ?? const [])
      if (option is Map)
        (
          label: (option['label'] as String?) ?? '',
          description: (option['description'] as String?) ?? '',
        ),
  ];

  void _tap(String label) {
    if (widget.busy) return;
    if (!_multi) {
      widget.onAnswer({
        'selected': [label],
      });
      return;
    }
    setState(() {
      if (!_selected.remove(label)) _selected.add(label);
    });
  }

  void _submit() {
    final other = _other.text.trim();
    if (_selected.isEmpty && other.isEmpty) return;
    widget.onAnswer({'selected': _selected.toList(), 'other': other});
  }

  @override
  Widget build(BuildContext context) {
    final question = (widget.request.data['question'] as String?) ?? '';
    final allowOther = widget.request.data['allow_other'] != false;
    final canSubmit = _selected.isNotEmpty || _other.text.trim().isNotEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Header(
          icon: Icons.help_outline_rounded,
          label: _multi
              ? '${AppInfo.name.toUpperCase()} ASKS · PICK ANY'
              : '${AppInfo.name.toUpperCase()} ASKS',
        ),
        _Title(question),
        const SizedBox(height: 12),
        for (final option in _options)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: _OptionTile(
              label: option.label,
              description: option.description,
              selected: _selected.contains(option.label),
              multi: _multi,
              enabled: !widget.busy,
              onTap: () => _tap(option.label),
            ),
          ),
        if (allowOther && !_otherOpen)
          Pressable(
            onTap: widget.busy ? null : () => setState(() => _otherOpen = true),
            semanticLabel: 'Something else',
            pressedScale: 0.97,
            child: const Padding(
              padding: EdgeInsets.symmetric(vertical: 6, horizontal: 4),
              child: Text(
                'Something else…',
                style: TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w500,
                  color: AppColors.inkSecondary,
                ),
              ),
            ),
          ),
        if (_otherOpen)
          Container(
            margin: const EdgeInsets.only(top: 2),
            padding: const EdgeInsets.symmetric(horizontal: 14),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(14),
            ),
            child: TextField(
              controller: _other,
              autofocus: true,
              minLines: 1,
              maxLines: 4,
              enabled: !widget.busy,
              onChanged: (_) => setState(() {}),
              style: const TextStyle(fontSize: 15, color: AppColors.ink),
              decoration: const InputDecoration(
                hintText: 'Type your answer',
                hintStyle: TextStyle(color: AppColors.inkTertiary),
                border: InputBorder.none,
                isDense: true,
                contentPadding: EdgeInsets.symmetric(vertical: 12),
              ),
            ),
          ),
        if (_multi || _otherOpen)
          _Buttons(
            children: [
              CardButton(
                label: 'Send',
                dark: true,
                busy: widget.busy,
                onTap: canSubmit ? _submit : null,
              ),
            ],
          ),
        if (!_multi && !_otherOpen && widget.busy)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: LinearProgressIndicator(
              minHeight: 2,
              color: AppColors.ink,
              backgroundColor: AppColors.hairline,
            ),
          ),
      ],
    );
  }
}

class _OptionTile extends StatelessWidget {
  const _OptionTile({
    required this.label,
    required this.description,
    required this.selected,
    required this.multi,
    required this.enabled,
    required this.onTap,
  });

  final String label;
  final String description;
  final bool selected;
  final bool multi;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: enabled ? onTap : null,
      semanticLabel: label,
      pressedScale: 0.98,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: selected ? AppColors.ink : AppColors.surface,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: selected ? Colors.white : AppColors.ink,
                    ),
                  ),
                  if (description.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(
                        description,
                        style: TextStyle(
                          fontSize: 13,
                          height: 1.35,
                          color: selected
                              ? Colors.white70
                              : AppColors.inkSecondary,
                        ),
                      ),
                    ),
                ],
              ),
            ),
            if (multi)
              Icon(
                selected ? Icons.check_circle_rounded : Icons.circle_outlined,
                size: 20,
                color: selected ? Colors.white : AppColors.inkTertiary,
              )
            else
              Icon(
                Icons.arrow_forward_rounded,
                size: 18,
                color: selected ? Colors.white : AppColors.inkTertiary,
              ),
          ],
        ),
      ),
    );
  }
}

class _Approval extends StatelessWidget {
  const _Approval({
    required this.request,
    required this.busy,
    required this.onAnswer,
  });

  final ChatRequest request;
  final bool busy;
  final ValueChanged<Object?> onAnswer;

  @override
  Widget build(BuildContext context) {
    final title = (request.data['title'] as String?) ?? 'Approve this action?';
    final detail = request.data['detail'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _Header(
          icon: Icons.verified_user_outlined,
          label: 'NEEDS YOUR APPROVAL',
        ),
        _Title(title),
        if (detail != null) _Detail(detail),
        _Buttons(
          children: [
            CardButton(
              label: 'Deny',
              onTap: busy ? null : () => onAnswer(const {'approved': false}),
            ),
            CardButton(
              label: 'Approve',
              dark: true,
              busy: busy,
              onTap: () => onAnswer(const {'approved': true}),
            ),
          ],
        ),
      ],
    );
  }
}

class _Detail extends StatelessWidget {
  const _Detail(this.detail);

  final Object detail;

  static const Map<String, String> _labels = {
    'page': 'Page',
    'submits_to': 'Sends to',
    'url': 'Address',
    'paths': 'Files',
    'path': 'File',
    'action': 'Action',
  };

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    final value = detail;
    if (value is Map) {
      final command = value['command'];
      if (command is String && command.isNotEmpty) rows.add(_code(command));
      for (final entry in value.entries) {
        if (entry.key == 'command' || entry.value == null) continue;
        final text = entry.value is String || entry.value is num
            ? '${entry.value}'
            : entry.value is List &&
                  (entry.value as List).every((v) => v is String)
            ? (entry.value as List).join('\n')
            : const JsonEncoder.withIndent('  ').convert(entry.value);
        rows.add(
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: '${_labels[entry.key] ?? entry.key}  ',
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      color: AppColors.inkTertiary,
                    ),
                  ),
                  TextSpan(text: text),
                ],
              ),
              maxLines: 6,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 13.5,
                height: 1.35,
                color: AppColors.inkSecondary,
              ),
            ),
          ),
        );
      }
    } else if (value is String) {
      rows.add(
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text(
            value,
            style: const TextStyle(
              fontSize: 14,
              height: 1.4,
              color: AppColors.inkSecondary,
            ),
          ),
        ),
      );
    } else {
      rows.add(_code(const JsonEncoder.withIndent('  ').convert(value)));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows);
  }

  Widget _code(String text) => Container(
    width: double.infinity,
    margin: const EdgeInsets.only(top: 10),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Text(
      text,
      maxLines: 12,
      overflow: TextOverflow.ellipsis,
      style: const TextStyle(
        fontSize: 12.5,
        height: 1.4,
        fontFamily: 'monospace',
        color: AppColors.ink,
      ),
    ),
  );
}

class _AppAccess extends StatelessWidget {
  const _AppAccess({
    required this.request,
    required this.busy,
    required this.onAnswer,
  });

  final ChatRequest request;
  final bool busy;
  final ValueChanged<Object?> onAnswer;

  static String _tier(String? tier) => switch (tier) {
    'view' => 'View only',
    'click' => 'Click and scroll',
    _ => 'Click and type',
  };

  @override
  Widget build(BuildContext context) {
    final reason = (request.data['reason'] as String?) ?? '';
    final apps = [
      for (final app in (request.data['apps'] as List?) ?? const [])
        if (app is Map) app,
    ];
    final systemKeys = request.data['system_keys'] == true;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _Header(
          icon: Icons.desktop_windows_outlined,
          label: 'USE APPS ON YOUR COMPUTER',
        ),
        _Title(
          apps.length == 1
              ? 'Allow ${AppInfo.name} to use ${apps.first['name']}?'
              : 'Allow ${AppInfo.name} to use these apps?',
        ),
        if (reason.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              reason,
              style: const TextStyle(
                fontSize: 14,
                height: 1.4,
                color: AppColors.inkSecondary,
              ),
            ),
          ),
        const SizedBox(height: 10),
        for (final app in apps)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.apps_rounded,
                    size: 20,
                    color: AppColors.ink,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${app['name'] ?? app['id'] ?? 'App'}',
                          style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: AppColors.ink,
                          ),
                        ),
                        Text(
                          _tier(app['tier'] as String?),
                          style: const TextStyle(
                            fontSize: 12.5,
                            color: AppColors.inkSecondary,
                          ),
                        ),
                        if ((app['warning'] as String?)?.isNotEmpty ?? false)
                          Padding(
                            padding: const EdgeInsets.only(top: 2),
                            child: Text(
                              app['warning'] as String,
                              style: const TextStyle(
                                fontSize: 12.5,
                                height: 1.35,
                                color: AppColors.warning,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        if (systemKeys)
          const Padding(
            padding: EdgeInsets.only(top: 4),
            child: Text(
              'Also asks to use system shortcuts (such as switching apps).',
              style: TextStyle(
                fontSize: 13,
                height: 1.35,
                color: AppColors.warning,
              ),
            ),
          ),
        const Padding(
          padding: EdgeInsets.only(top: 6),
          child: Text(
            'Allowed for this chat only. Passwords and keychains are always off limits.',
            style: TextStyle(
              fontSize: 12.5,
              height: 1.35,
              color: AppColors.inkTertiary,
            ),
          ),
        ),
        _Buttons(
          children: [
            CardButton(
              label: "Don't allow",
              onTap: busy ? null : () => onAnswer(const {'approved': false}),
            ),
            CardButton(
              label: 'Allow',
              dark: true,
              busy: busy,
              onTap: () => onAnswer(const {'approved': true}),
            ),
          ],
        ),
      ],
    );
  }
}

class _Takeover extends StatelessWidget {
  const _Takeover({
    required this.request,
    required this.busy,
    required this.onDone,
    required this.onTakeOver,
  });

  final ChatRequest request;
  final bool busy;
  final VoidCallback onDone;
  final VoidCallback onTakeOver;

  @override
  Widget build(BuildContext context) {
    final onComputer = request.data['target'] == 'computer';
    final reason =
        (request.data['reason'] as String?) ??
        'Please finish this step yourself.';
    final url = request.data['url'] as String?;
    final host = url == null ? null : Uri.tryParse(url)?.host;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Header(
          icon: Icons.back_hand_outlined,
          label: onComputer
              ? 'TAKE OVER YOUR COMPUTER'
              : 'TAKE OVER THE BROWSER',
        ),
        _Title(reason),
        if (host != null && host.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              host,
              style: const TextStyle(
                fontSize: 13.5,
                color: AppColors.inkSecondary,
              ),
            ),
          ),
        const Padding(
          padding: EdgeInsets.only(top: 6),
          child: Text(
            '${AppInfo.name} pauses while you are in control and carries on when you are done.',
            style: TextStyle(
              fontSize: 12.5,
              height: 1.35,
              color: AppColors.inkTertiary,
            ),
          ),
        ),
        _Buttons(
          children: [
            CardButton(label: "I've done it", onTap: busy ? null : onDone),
            CardButton(
              label: 'Take over',
              icon: Icons.back_hand_outlined,
              dark: true,
              busy: busy,
              onTap: onTakeOver,
            ),
          ],
        ),
      ],
    );
  }
}

class _Unknown extends StatelessWidget {
  const _Unknown({required this.request});

  final ChatRequest request;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _Header(icon: Icons.info_outline_rounded, label: 'WAITING'),
        _Title(request.summary),
        const Padding(
          padding: EdgeInsets.only(top: 6),
          child: Text(
            'This request needs a newer version of the app.',
            style: TextStyle(fontSize: 13, color: AppColors.inkSecondary),
          ),
        ),
      ],
    );
  }
}
