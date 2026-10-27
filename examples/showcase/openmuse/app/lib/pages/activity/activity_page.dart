import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../api/api_client.dart';
import '../../glass/glass_controls.dart';
import '../../glass/glass_sheet.dart';
import '../../glass/glass_toast.dart';
import '../../glass/pressable.dart';
import '../../models/chat_models.dart';
import '../../state/activity_store.dart';
import '../../state/chat_store.dart';
import '../../state/navigation.dart';
import '../../theme/app_theme.dart';
import '../../utils/time_format.dart';
import '../../utils/tool_labels.dart';
import '../../widgets/page_header.dart';
import '../../utils/route_guard.dart';

enum _Filter { all, attention, running, routines, done }

extension on _Filter {
  String get label => switch (this) {
    _Filter.all => 'All',
    _Filter.attention => 'Needs you',
    _Filter.running => 'In progress',
    _Filter.routines => 'Routines',
    _Filter.done => 'Done',
  };
}

class ActivityPage extends StatefulWidget {
  const ActivityPage({super.key, this.visible = true});

  final bool visible;

  @override
  State<ActivityPage> createState() => _ActivityPageState();
}

class _ActivityPageState extends State<ActivityPage> {
  _Filter _filter = _Filter.all;
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    _syncTicker();
  }

  @override
  void didUpdateWidget(ActivityPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.visible && !oldWidget.visible) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) unawaited(ActivityScope.read(context).refresh());
      });
    }
    _syncTicker();
  }

  void _syncTicker() {
    if (widget.visible) {
      _ticker ??= Timer.periodic(const Duration(seconds: 30), (_) {
        if (mounted) setState(() {});
      });
    } else {
      _ticker?.cancel();
      _ticker = null;
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  Future<void> _openChat(String chatId) async {
    ShellScope.read(context).go(ShellNavigation.home);
    await ChatScope.read(context).open(chatId);
  }

  Future<void> _newRoutine() async {
    final created = await showGlassSheet<Routine>(
      context,
      builder: (_) => const _NewRoutineSheet(),
    );
    if (created != null && mounted) {
      showGlassToast(context, 'Routine created', icon: Icons.schedule_rounded);
    }
  }

  Future<void> _routineActions(Routine routine) async {
    final activity = ActivityScope.read(context);
    final action = await showGlassSheet<String>(
      context,
      builder: (sheetContext) => _RoutineActions(routine: routine),
    );
    if (action == null || !mounted) return;
    try {
      switch (action) {
        case 'open':
          await _openChat(routine.chatId);
        case 'delete':
          await activity.deleteRoutine(routine);
          if (mounted) {
            showGlassToast(
              context,
              'Routine deleted',
              icon: Icons.delete_outline_rounded,
            );
          }
        case 'run':
          await activity.routineAction(routine, 'run');
          if (mounted) {
            showGlassToast(
              context,
              'Running now',
              icon: Icons.play_arrow_rounded,
            );
          }
        default:
          await activity.routineAction(routine, action);
      }
    } on ApiException catch (error) {
      if (mounted) {
        showGlassToast(
          context,
          error.message,
          icon: Icons.error_outline_rounded,
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final activity = ActivityScope.of(context);
    final now = DateTime.now();
    final top = MediaQuery.paddingOf(context).top;

    bool show(_Filter section) => _filter == _Filter.all || _filter == section;

    final routines = [...activity.routines]
      ..sort((a, b) {
        if (a.paused != b.paused) return a.paused ? 1 : -1;
        return (a.nextRun ?? now).compareTo(b.nextRun ?? now);
      });

    final days = <String, List<RunItem>>{};
    for (final run in activity.recent) {
      days
          .putIfAbsent(TimeFormat.sectionTitle(run.endedAt, now), () => [])
          .add(run);
    }

    final children = <Widget>[];
    void section(String title, List<Widget> rows, {Color? accent}) {
      if (rows.isEmpty) return;
      children.add(_SectionLabel(title, accent: accent));
      for (var i = 0; i < rows.length; i++) {
        if (i > 0) {
          children.add(
            const Divider(height: 1, thickness: 0.5, color: AppColors.hairline),
          );
        }
        children.add(rows[i]);
      }
    }

    if (show(_Filter.attention)) {
      section('Needs you', [
        for (final item in activity.needsYou)
          _ActivityRow(
            title: item.request.summary,
            detail: item.chatTitle,
            time: TimeFormat.relative(item.request.createdAt, now),
            status: const _StatusText(
              'Needs your answer',
              color: AppColors.danger,
            ),
            onTap: () => _openChat(item.chatId),
          ),
      ], accent: AppColors.danger);
    }
    if (show(_Filter.running)) {
      section('In progress', [
        for (final item in activity.running)
          _ActivityRow(
            title: item.chatTitle,
            detail: ToolLabel.activity(item.step),
            time: TimeFormat.relative(item.startedAt, now),
            status: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _StatusText(
                  item.source == 'schedule'
                      ? 'Routine in progress'
                      : 'In progress',
                ),
                const SizedBox(height: 6),
                const _ThinProgress(),
              ],
            ),
            onTap: () => _openChat(item.chatId),
          ),
      ]);
    }
    if (show(_Filter.routines)) {
      section('Routines', [
        for (final routine in routines)
          _ActivityRow(
            title: routine.prompt,
            detail: routine.rule,
            time: routine.paused || routine.nextRun == null
                ? ''
                : TimeFormat.relative(routine.nextRun!, now),
            status: _StatusText(routine.paused ? 'Paused' : 'Scheduled'),
            onTap: () => _routineActions(routine),
          ),
      ]);
    }
    if (show(_Filter.done)) {
      for (final entry in days.entries) {
        section(entry.key, [
          for (final run in entry.value)
            _ActivityRow(
              title: run.chatTitle,
              detail: _runDetail(run),
              time: TimeFormat.relative(run.endedAt, now),
              status: _runStatus(run),
              onTap: () => _openChat(run.chatId),
            ),
        ]);
      }
    }

    final side =
        AppLayout.centeredInset(
          MediaQuery.sizeOf(context).width,
          AppLayout.listWidth,
        ) +
        4;

    return RefreshIndicator.adaptive(
      onRefresh: activity.refresh,
      edgeOffset: top,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: EdgeInsets.fromLTRB(
          side,
          top + 16,
          side,
          AppLayout.contentBottomInset(context),
        ),
        children: [
          PageHeader(
            title: 'Activity',
            trailing: GlassCircleButton(
              icon: Icons.add_rounded,
              semanticLabel: 'New routine',
              onTap: _newRoutine,
            ),
          ),
          const SizedBox(height: 16),
          _FilterBar(
            selected: _filter,
            onChanged: (f) => setState(() => _filter = f),
          ),
          if (children.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 56),
              child: Center(
                child: Text(
                  !activity.loaded && activity.loading
                      ? 'Loading…'
                      : activity.error != null && !activity.loaded
                      ? activity.error!
                      : _emptyText,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: AppColors.inkTertiary,
                    fontSize: 15,
                    height: 1.4,
                  ),
                ),
              ),
            )
          else
            ...children,
        ],
      ),
    );
  }

  String get _emptyText => switch (_filter) {
    _Filter.attention => 'Nothing needs you right now.',
    _Filter.running => '${AppInfo.name} is not working on anything.',
    _Filter.routines => 'No routines yet.\nTap + or ask in a chat, e.g. “every morning at 8, brief me on the news”.',
    _ => 'Nothing here yet.',
  };

  static String _oneLine(String text) =>
      text.replaceAll(RegExp(r'\s+'), ' ').trim();

  static String _runDetail(RunItem run) {
    if (run.summary.isNotEmpty) return _oneLine(run.summary);
    return _fallbackSummary(run);
  }

  static String _fallbackSummary(RunItem run) {
    if (run.steps > 0) return '${run.steps} step${run.steps == 1 ? '' : 's'}';
    return run.source == 'schedule' ? 'Routine ran' : 'Answered';
  }

  static Widget? _runStatus(RunItem run) {
    if (run.failed) {
      return _StatusText(
        run.source == 'schedule' ? 'Routine didn’t finish' : 'Didn’t finish',
        color: AppColors.danger,
      );
    }
    return switch (run.status) {
      'stopped' => const _StatusText('Stopped'),
      'cancelled' => const _StatusText('Cancelled'),
      'interrupted' => const _StatusText('Interrupted'),
      _ => run.source == 'schedule' ? const _StatusText('Routine') : null,
    };
  }
}

class _FilterBar extends StatelessWidget {
  const _FilterBar({required this.selected, required this.onChanged});

  final _Filter selected;
  final ValueChanged<_Filter> onChanged;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      clipBehavior: Clip.none,
      child: Row(
        children: [
          for (final f in _Filter.values)
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: () => onChanged(f),
              child: Semantics(
                button: true,
                selected: f == selected,
                child: Padding(
                  padding: const EdgeInsets.only(right: 20, top: 6, bottom: 6),
                  child: AnimatedDefaultTextStyle(
                    duration: const Duration(milliseconds: 150),
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: f == selected
                          ? FontWeight.w600
                          : FontWeight.w400,
                      color: f == selected
                          ? AppColors.ink
                          : AppColors.inkTertiary,
                    ),
                    child: Text(f.label),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text, {this.accent});

  final String text;
  final Color? accent;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 26, bottom: 4),
      child: Row(
        children: [
          if (accent != null) ...[
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(color: accent, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
          ],
          Text(
            text,
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppColors.inkTertiary,
            ),
          ),
        ],
      ),
    );
  }
}

class _ActivityRow extends StatelessWidget {
  const _ActivityRow({
    required this.title,
    required this.detail,
    required this.time,
    required this.onTap,
    this.status,
  });

  final String title;
  final String detail;
  final String time;
  final Widget? status;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      pressedScale: 0.99,
      haptics: false,
      semanticLabel: title,
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic,
              children: [
                Expanded(
                  child: Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Text(
                  time,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.inkTertiary,
                  ),
                ),
              ],
            ),
            if (detail.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                detail,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 14.5,
                  height: 1.4,
                  color: AppColors.inkSecondary,
                ),
              ),
            ],
            if (status != null) ...[const SizedBox(height: 8), status!],
          ],
        ),
      ),
    );
  }
}

class _StatusText extends StatelessWidget {
  const _StatusText(this.text, {this.color = AppColors.inkTertiary});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: color),
    );
  }
}

class _ThinProgress extends StatefulWidget {
  const _ThinProgress();

  @override
  State<_ThinProgress> createState() => _ThinProgressState();
}

class _ThinProgressState extends State<_ThinProgress>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1400),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(1),
      child: SizedBox(
        height: 2,
        child: AnimatedBuilder(
          animation: _controller,
          builder: (context, _) {
            final t = Curves.easeInOut.transform(_controller.value);
            return Stack(
              children: [
                const Positioned.fill(
                  child: ColoredBox(color: Color(0x14000000)),
                ),
                Align(
                  alignment: Alignment(-1.2 + 2.4 * t, 0),
                  child: const FractionallySizedBox(
                    widthFactor: 0.3,
                    heightFactor: 1,
                    child: ColoredBox(color: AppColors.ink),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _RoutineActions extends StatelessWidget {
  const _RoutineActions({required this.routine});

  final Routine routine;

  @override
  Widget build(BuildContext context) {
    void pick(String action) => popRoute(context, action);
    final next = routine.nextRun;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 4),
          child: Text(
            routine.prompt,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w700,
              color: AppColors.ink,
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 14),
          child: Text(
            [
              routine.rule,
              if (routine.paused) 'Paused',
              if (!routine.paused && next != null)
                'Next: ${TimeFormat.messageStamp(next, DateTime.now())}',
            ].join(' · '),
            style: const TextStyle(fontSize: 14, color: AppColors.inkSecondary),
          ),
        ),
        _SheetAction(
          icon: Icons.play_arrow_rounded,
          label: 'Run now',
          onTap: () => pick('run'),
        ),
        const SizedBox(height: 8),
        _SheetAction(
          icon: routine.paused
              ? Icons.play_circle_outline_rounded
              : Icons.pause_circle_outline_rounded,
          label: routine.paused ? 'Resume' : 'Pause',
          onTap: () => pick(routine.paused ? 'resume' : 'pause'),
        ),
        const SizedBox(height: 8),
        _SheetAction(
          icon: Icons.chat_bubble_outline_rounded,
          label: 'Open chat',
          onTap: () => pick('open'),
        ),
        const SizedBox(height: 8),
        _SheetAction(
          icon: Icons.delete_outline_rounded,
          label: 'Delete',
          color: AppColors.danger,
          onTap: () => pick('delete'),
        ),
      ],
    );
  }
}

class _SheetAction extends StatelessWidget {
  const _SheetAction({
    required this.icon,
    required this.label,
    required this.onTap,
    this.color = AppColors.ink,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.97,
      child: Container(
        height: 52,
        padding: const EdgeInsets.symmetric(horizontal: 18),
        decoration: const ShapeDecoration(
          color: AppColors.surface,
          shape: StadiumBorder(),
        ),
        child: Row(
          children: [
            Icon(icon, size: 21, color: color),
            const SizedBox(width: 12),
            Text(
              label,
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NewRoutineSheet extends StatefulWidget {
  const _NewRoutineSheet();

  @override
  State<_NewRoutineSheet> createState() => _NewRoutineSheetState();
}

class _NewRoutineSheetState extends State<_NewRoutineSheet> {
  final TextEditingController _prompt = TextEditingController();
  String _repeat = 'daily';
  DateTime _when = DateTime.now().add(const Duration(hours: 1));
  int _weekday = DateTime.now().weekday;
  bool _busy = false;
  String? _error;

  static const List<(String, String)> _repeats = [
    ('daily', 'Every day'),
    ('weekdays', 'Weekdays'),
    ('weekly', 'Weekly'),
    ('hourly', 'Every hour'),
    ('once', 'Once'),
  ];
  static const List<String> _days = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

  @override
  void initState() {
    super.initState();
    _when = DateTime(_when.year, _when.month, _when.day, _when.hour);
  }

  @override
  void dispose() {
    _prompt.dispose();
    super.dispose();
  }

  String _two(int n) => n.toString().padLeft(2, '0');

  Future<void> _create() async {
    final prompt = _prompt.text.trim();
    if (prompt.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final routine = await ActivityScope.read(context).createRoutine(
        prompt: prompt,
        repeat: _repeat,
        time: '${_two(_when.hour)}:${_two(_when.minute)}',
        date: _repeat == 'once'
            ? '${_when.year}-${_two(_when.month)}-${_two(_when.day)}'
            : null,
        weekday: _weekday,
      );
      if (mounted) popRoute(context, routine);
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = error.message;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(4, 0, 4, 4),
          child: Text(
            'New routine',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: AppColors.ink,
            ),
          ),
        ),
        const Padding(
          padding: EdgeInsets.fromLTRB(4, 0, 4, 12),
          child: Text(
            '${AppInfo.name} does this on its own and tells you how it went.',
            style: TextStyle(fontSize: 14, color: AppColors.inkSecondary),
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(16),
          ),
          child: TextField(
            controller: _prompt,
            minLines: 2,
            maxLines: 5,
            autofocus: true,
            textCapitalization: TextCapitalization.sentences,
            onChanged: (_) => setState(() {}),
            style: const TextStyle(
              fontSize: 16,
              height: 1.35,
              color: AppColors.ink,
            ),
            decoration: const InputDecoration(
              hintText: 'e.g. Check the price of the AirPods Pro on example.com and tell me if it drops below 199',
              hintMaxLines: 3,
              hintStyle: TextStyle(color: AppColors.inkTertiary),
              border: InputBorder.none,
              contentPadding: EdgeInsets.symmetric(vertical: 14),
            ),
          ),
        ),
        const SizedBox(height: 14),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final (value, label) in _repeats)
              _Choice(
                label: label,
                selected: _repeat == value,
                onTap: () => setState(() => _repeat = value),
              ),
          ],
        ),
        if (_repeat == 'weekly') ...[
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              for (var day = 1; day <= 7; day++)
                _DayDot(
                  label: _days[day - 1],
                  selected: _weekday == day,
                  onTap: () => setState(() => _weekday = day),
                ),
            ],
          ),
        ],
        if (_repeat != 'hourly')
          SizedBox(
            height: 150,
            child: CupertinoDatePicker(
              key: ValueKey(_repeat == 'once'),
              mode: _repeat == 'once'
                  ? CupertinoDatePickerMode.dateAndTime
                  : CupertinoDatePickerMode.time,
              use24hFormat: MediaQuery.alwaysUse24HourFormatOf(context),
              minimumDate: _repeat == 'once' ? DateTime.now() : null,
              initialDateTime:
                  _when.isBefore(DateTime.now()) && _repeat == 'once'
                  ? DateTime.now().add(const Duration(minutes: 5))
                  : _when,
              onDateTimeChanged: (value) => _when = value,
            ),
          ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 6, left: 4),
            child: Text(
              _error!,
              style: const TextStyle(fontSize: 13.5, color: AppColors.danger),
            ),
          ),
        const SizedBox(height: 10),
        Pressable(
          onTap: _prompt.text.trim().isEmpty || _busy ? null : _create,
          semanticLabel: 'Create routine',
          pressedScale: 0.97,
          child: Container(
            height: 52,
            alignment: Alignment.center,
            decoration: const ShapeDecoration(
              color: AppColors.ink,
              shape: StadiumBorder(),
            ),
            child: _busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.2,
                      color: Colors.white,
                    ),
                  )
                : const Text(
                    'Create routine',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                    ),
                  ),
          ),
        ),
      ],
    );
  }
}

class _Choice extends StatelessWidget {
  const _Choice({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.95,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        height: 36,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        decoration: ShapeDecoration(
          color: selected ? AppColors.ink : AppColors.surface,
          shape: const StadiumBorder(),
        ),
        child: Center(
          widthFactor: 1,
          child: Text(
            label,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: selected ? Colors.white : AppColors.ink,
            ),
          ),
        ),
      ),
    );
  }
}

class _DayDot extends StatelessWidget {
  const _DayDot({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.9,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        width: 38,
        height: 38,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected ? AppColors.ink : AppColors.surface,
          shape: BoxShape.circle,
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: selected ? Colors.white : AppColors.ink,
          ),
        ),
      ),
    );
  }
}
