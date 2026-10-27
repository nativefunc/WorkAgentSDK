import 'package:flutter/material.dart';

import '../../../glass/pressable.dart';
import '../../../models/chat_models.dart';
import '../../../theme/app_theme.dart';
import '../../../utils/tool_labels.dart';

class StepGroup extends StatefulWidget {
  const StepGroup({
    super.key,
    required this.steps,
    required this.active,
    this.answers = const {},
  });

  final List<ChatMessage> steps;

  final bool active;

  final Map<String, String> answers;

  @override
  State<StepGroup> createState() => _StepGroupState();
}

class _StepGroupState extends State<StepGroup> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final steps = widget.steps;
    final last = steps.last;
    final failed = steps.where((s) => s.failed).length;
    final running =
        widget.active && (last.inProgress || last.status == 'waiting');
    final lastLabel = ToolLabel.of(last.toolName, last.preview);
    final single = steps.length == 1;
    final expandable =
        !single || _StepRow.hasDetails(last, widget.answers[last.callId]);

    final String title;
    if (running) {
      title = lastLabel.text(inProgress: true);
    } else if (steps.length == 1) {
      title = lastLabel.text(inProgress: false);
    } else {
      title = '${steps.length} steps';
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Pressable(
            onTap: expandable ? () => setState(() => _open = !_open) : null,
            semanticLabel: _open ? 'Hide steps' : 'Show steps',
            pressedScale: 0.98,
            haptics: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _StatusIcon(
                    running: running,
                    failed: failed > 0 && !running,
                    icon: lastLabel.icon,
                  ),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w500,
                        color: AppColors.inkSecondary,
                      ),
                    ),
                  ),
                  if (failed > 0 && !running)
                    Text(
                      ' · $failed failed',
                      style: const TextStyle(
                        fontSize: 14,
                        color: AppColors.danger,
                      ),
                    ),
                  if (expandable) ...[
                    const SizedBox(width: 2),
                    AnimatedRotation(
                      turns: _open ? 0.25 : 0,
                      duration: const Duration(milliseconds: 180),
                      child: const Icon(
                        Icons.chevron_right_rounded,
                        size: 18,
                        color: AppColors.inkTertiary,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          AnimatedSize(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            alignment: Alignment.topLeft,
            child: _open && expandable
                ? Container(
                    margin: const EdgeInsets.only(left: 9, top: 2),
                    padding: const EdgeInsets.only(left: 14),
                    decoration: const BoxDecoration(
                      border: Border(
                        left: BorderSide(color: AppColors.hairline, width: 1.5),
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (final step in steps)
                          _StepRow(
                            step: step,
                            answer: widget.answers[step.callId],
                            showLabel: !single,
                          ),
                      ],
                    ),
                  )
                : const SizedBox(width: double.infinity),
          ),
        ],
      ),
    );
  }
}

class _StatusIcon extends StatelessWidget {
  const _StatusIcon({
    required this.running,
    required this.failed,
    required this.icon,
  });

  final bool running;
  final bool failed;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    if (running) {
      return const SizedBox(
        width: 16,
        height: 16,
        child: CircularProgressIndicator(
          strokeWidth: 1.8,
          color: AppColors.inkTertiary,
        ),
      );
    }
    return Icon(
      failed ? Icons.error_outline_rounded : icon,
      size: 17,
      color: failed ? AppColors.danger : AppColors.inkTertiary,
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({required this.step, this.answer, this.showLabel = true});

  final ChatMessage step;
  final String? answer;

  final bool showLabel;

  static String? _detailOf(ChatMessage step, String? answer) {
    if (step.toolName == 'shell') return step.preview;
    if (step.toolName == 'ask_user') return answer ?? _firstLine(step.output);
    return null;
  }

  static bool hasDetails(ChatMessage step, String? answer) {
    final detail = _detailOf(step, answer);
    return (detail != null && detail.isNotEmpty) ||
        (step.toolName == 'shell' && step.output.trim().isNotEmpty) ||
        (step.error != null && step.error!.isNotEmpty);
  }

  @override
  Widget build(BuildContext context) {
    final inProgress = step.inProgress || step.status == 'waiting';
    final label = ToolLabel.of(step.toolName, step.preview);
    final isShell = step.toolName == 'shell';
    final detail = _detailOf(step, answer);
    final output = isShell ? _lastLines(step.output, 4) : null;
    final indent = showLabel ? 23.0 : 0.0;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (showLabel)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 1),
                  child: Icon(
                    label.icon,
                    size: 15,
                    color: AppColors.inkTertiary,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    label.text(inProgress: inProgress),
                    style: const TextStyle(
                      fontSize: 13.5,
                      height: 1.35,
                      color: AppColors.inkSecondary,
                    ),
                  ),
                ),
                if (step.hasImage)
                  const Padding(
                    padding: EdgeInsets.only(left: 6),
                    child: Icon(
                      Icons.photo_outlined,
                      size: 14,
                      color: AppColors.inkTertiary,
                    ),
                  ),
              ],
            ),
          if (detail != null && detail.isNotEmpty)
            Padding(
              padding: EdgeInsets.only(left: indent, top: showLabel ? 3 : 0),
              child: Text(
                detail,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12.5,
                  height: 1.35,
                  color: AppColors.inkSecondary,
                  fontFamily: isShell ? 'monospace' : null,
                ),
              ),
            ),
          if (output != null && output.isNotEmpty)
            Container(
              margin: EdgeInsets.only(left: indent, top: 4),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                output,
                style: const TextStyle(
                  fontSize: 11.5,
                  height: 1.35,
                  fontFamily: 'monospace',
                  color: AppColors.inkSecondary,
                ),
              ),
            ),
          if (step.error != null && step.error!.isNotEmpty)
            Padding(
              padding: EdgeInsets.only(left: indent, top: 3),
              child: Text(
                step.error!,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 12.5,
                  height: 1.35,
                  color: AppColors.danger,
                ),
              ),
            ),
        ],
      ),
    );
  }

  static String _firstLine(String text) => text.split('\n').first.trim();

  static String _lastLines(String text, int count) {
    final lines = text.trimRight().split('\n');
    final kept = lines.length <= count
        ? lines
        : lines.sublist(lines.length - count);
    return kept.join('\n');
  }
}
