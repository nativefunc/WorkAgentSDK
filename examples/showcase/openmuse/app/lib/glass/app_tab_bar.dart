import 'dart:math' as math;
import 'dart:ui' show lerpDouble;

import 'package:flutter/material.dart';
import 'package:flutter/physics.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';

import '../theme/app_theme.dart';
import 'glass_presets.dart';
import 'glass_settings.dart';
import 'glass_surface.dart';

class AppTabItem {
  const AppTabItem({
    required this.icon,
    required this.activeIcon,
    required this.label,
    this.badge = false,
  });

  final IconData icon;
  final IconData activeIcon;
  final String label;

  final bool badge;
}

class AppTabBar extends StatefulWidget {
  const AppTabBar({
    super.key,
    required this.items,
    required this.currentIndex,
    required this.onChanged,
    this.height = AppLayout.tabBarHeight,
  }) : assert(items.length >= 2, 'AppTabBar needs at least two items');

  final List<AppTabItem> items;
  final int currentIndex;
  final ValueChanged<int> onChanged;
  final double height;

  @override
  State<AppTabBar> createState() => _AppTabBarState();
}

class _AppTabBarState extends State<AppTabBar> with TickerProviderStateMixin {
  static final SpringDescription _spring = SpringDescription.withDampingRatio(
    mass: 1,
    stiffness: 300,
    ratio: 0.8,
  );

  static const double _inset = 4;

  static const double _lensOverhang = 10;

  static const double _lensWiden = 0.16;

  static const double _fullLiftSpeed = 4;

  static const double _touchLift = 0.3;

  static const double _riseRate = 22;
  static const double _sinkRate = 9;

  static const double _maxOvershoot = 0.12;

  static const double _maxSettleVelocity = 8;

  late final AnimationController _position = AnimationController.unbounded(
    vsync: this,
    value: widget.currentIndex.toDouble(),
  );

  final ValueNotifier<double> _lift = ValueNotifier<double>(0);
  late final Ticker _ticker = createTicker(_tick);
  Duration _lastTick = Duration.zero;

  double _stretch = 0;

  bool _dragging = false;
  bool _pointerDown = false;
  double _tabWidth = 1;

  late int _target = widget.currentIndex;

  int get _lastIndex => widget.items.length - 1;

  @override
  void didUpdateWidget(AppTabBar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_dragging && widget.currentIndex != _target) {
      _settleAt(widget.currentIndex);
    }
  }

  @override
  void dispose() {
    _ticker.dispose();
    _position.dispose();
    _lift.dispose();
    super.dispose();
  }

  void _wake() {
    if (_ticker.isActive) return;
    _lastTick = Duration.zero;
    _ticker.start();
  }

  void _tick(Duration elapsed) {
    final dt = _lastTick == Duration.zero
        ? 1 / 60
        : (elapsed - _lastTick).inMicroseconds / 1e6;
    _lastTick = elapsed;

    final speed = _position.isAnimating ? _position.velocity.abs() : 0.0;
    var target = (speed / _fullLiftSpeed).clamp(0.0, 1.0).toDouble();
    if (_dragging) target = 1;
    if (_pointerDown) target = math.max(target, _touchLift);

    final stretchTarget = _dragging
        ? 0.0
        : (speed / 30).clamp(0.0, 0.12).toDouble();
    _stretch += (stretchTarget - _stretch) * (1 - math.exp(-14 * dt));
    if (_stretch < 0.001 && stretchTarget == 0) _stretch = 0;

    final current = _lift.value;
    final rate = target > current ? _riseRate : _sinkRate;
    final next = current + (target - current) * (1 - math.exp(-rate * dt));
    _lift.value = (next - target).abs() < 0.002 ? target : next;

    final idle =
        !_dragging &&
        !_pointerDown &&
        !_position.isAnimating &&
        _lift.value == 0 &&
        _stretch == 0;
    if (idle) _ticker.stop();
  }

  void _settleAt(int index, {double velocity = 0}) {
    _target = index;
    _position.animateWith(
      SpringSimulation(_spring, _position.value, index.toDouble(), velocity),
    );
    _wake();
  }

  void _select(int index) {
    if (index != _target) _settleAt(index);
    if (index == widget.currentIndex) return;
    HapticFeedback.selectionClick();
    widget.onChanged(index);
  }

  int _indexAt(double dx) =>
      ((dx - _inset) / _tabWidth).floor().clamp(0, _lastIndex).toInt();

  void _onPointerDown(PointerDownEvent event) {
    _pointerDown = true;
    _wake();
  }

  void _onPointerEnd(PointerEvent event) {
    _pointerDown = false;
    _wake();
  }

  void _onTapUp(TapUpDetails details) {
    _select(_indexAt(details.localPosition.dx));
  }

  void _onDragStart(DragStartDetails details) {
    _position.stop();
    _dragging = true;
    _wake();
  }

  void _onDragUpdate(DragUpdateDetails details) {
    final delta = details.delta.dx / _tabWidth;
    _position.value = (_position.value + delta)
        .clamp(-1.5, _lastIndex + 1.5)
        .toDouble();
  }

  void _onDragEnd(DragEndDetails details) {
    final velocity = (details.primaryVelocity ?? 0) / _tabWidth;
    final projected = _position.value + velocity * 0.12;
    final index = projected.round().clamp(0, _lastIndex).toInt();

    _dragging = false;
    _settleAt(
      index,
      velocity: velocity
          .clamp(-_maxSettleVelocity, _maxSettleVelocity)
          .toDouble(),
    );
    if (index != widget.currentIndex) {
      HapticFeedback.selectionClick();
      widget.onChanged(index);
    }
  }

  void _onDragCancel() {
    if (!_dragging) return;
    _dragging = false;
    _settleAt(widget.currentIndex);
  }

  double _soften(double raw) {
    if (raw < 0) {
      return -_maxOvershoot * (1 - math.exp(raw / _maxOvershoot));
    }
    if (raw > _lastIndex) {
      final over = raw - _lastIndex;
      return _lastIndex + _maxOvershoot * (1 - math.exp(-over / _maxOvershoot));
    }
    return raw;
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final height = widget.height;
        _tabWidth = (width - _inset * 2) / widget.items.length;

        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapUp: _onTapUp,
          onHorizontalDragStart: _onDragStart,
          onHorizontalDragUpdate: _onDragUpdate,
          onHorizontalDragEnd: _onDragEnd,
          onHorizontalDragCancel: _onDragCancel,
          child: Listener(
            behavior: HitTestBehavior.opaque,
            onPointerDown: _onPointerDown,
            onPointerUp: _onPointerEnd,
            onPointerCancel: _onPointerEnd,
            child: SizedBox(
              width: width,
              height: height,
              child: AnimatedBuilder(
                animation: Listenable.merge([_position, _lift]),
                builder: (context, _) => _buildBar(height),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildBar(double height) {
    final position = _soften(_position.value);
    final lift = Curves.easeOut.transform(_lift.value);

    final stretch = _stretch;

    final rest = Rect.fromLTWH(
      _inset + position * _tabWidth,
      _inset,
      _tabWidth,
      height - _inset * 2,
    );
    final dropRect = Rect.fromCenter(
      center: rest.center,
      width: rest.width * (1 + stretch + lift * _lensWiden),
      height:
          lerpDouble(rest.height, height + _lensOverhang * 2, lift)! *
          (1 - stretch * 0.35),
    );

    return Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned.fill(
          child: GlassSurface(
            settings: GlassPresets.bar,
            radius: height / 2,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: _inset),
              child: Row(
                children: [
                  for (var i = 0; i < widget.items.length; i++)
                    Expanded(
                      child: _TabButton(
                        item: widget.items[i],
                        selected: i == widget.currentIndex,
                        emphasis: (1 - (position - i).abs())
                            .clamp(0.0, 1.0)
                            .toDouble(),
                        onTap: () => _select(i),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),

        Positioned.fromRect(
          rect: dropRect,
          child: IgnorePointer(
            child: GlassSurface(
              settings: GlassSettings.lerp(
                GlassPresets.selection,
                GlassPresets.lens(),
                lift,
              ),
              strength: lift,
              radius: dropRect.height / 2,
              child: const SizedBox.expand(),
            ),
          ),
        ),
      ],
    );
  }
}

class _TabButton extends StatelessWidget {
  const _TabButton({
    required this.item,
    required this.selected,
    required this.emphasis,
    required this.onTap,
  });

  final AppTabItem item;
  final bool selected;
  final double emphasis;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = Color.lerp(AppColors.inkSecondary, AppColors.ink, emphasis)!;
    final filled = emphasis > 0.85;

    return Semantics(
      button: true,
      selected: selected,
      label: item.label,
      excludeSemantics: true,
      onTap: onTap,
      child: SizedBox.expand(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Transform.scale(
              scale: lerpDouble(1, 1.05, emphasis)!,
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Icon(
                    filled ? item.activeIcon : item.icon,
                    size: 22,
                    color: color,
                  ),
                  if (item.badge)
                    Positioned(
                      top: -1,
                      right: -3,
                      child: Container(
                        width: 9,
                        height: 9,
                        decoration: BoxDecoration(
                          color: AppColors.danger,
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 1.5),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 1),
            Text(
              item.label,
              maxLines: 1,
              overflow: TextOverflow.fade,
              softWrap: false,
              style: TextStyle(
                fontSize: 10,
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
