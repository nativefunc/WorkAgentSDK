import 'dart:math' as math;

import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';

import 'glass_pass.dart';
import 'glass_settings.dart';
import 'glass_shader.dart';
import 'glass_surface.dart';

class GlassGroup extends StatefulWidget {
  const GlassGroup({
    super.key,
    required this.settings,
    required this.child,
    this.blend = 12,
    this.edge = 1,
  });

  final GlassSettings settings;
  final Widget child;

  final double blend;

  final double edge;

  @override
  State<GlassGroup> createState() => _GlassGroupState();
}

class _GlassGroupState extends State<GlassGroup> {
  final _GroupLink _link = _GroupLink();

  @override
  Widget build(BuildContext context) {
    return _GroupScope(
      link: _link,
      settings: widget.settings,
      child: _GroupRenderWidget(
        link: _link,
        settings: widget.settings,
        blend: widget.blend,
        edge: widget.edge,
        devicePixelRatio: MediaQuery.devicePixelRatioOf(context),
        child: widget.child,
      ),
    );
  }
}

class GlassGroupShape extends StatelessWidget {
  const GlassGroupShape({
    super.key,
    this.child,
    this.radius = 24,
    this.circle = false,
    this.padding,
    this.width,
    this.height,
  });

  final Widget? child;

  final double radius;

  final bool circle;
  final EdgeInsetsGeometry? padding;
  final double? width;
  final double? height;

  @override
  Widget build(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<_GroupScope>();
    assert(scope != null, 'GlassGroupShape must be inside a GlassGroup.');

    if (scope == null || !GlassShader.ready) {
      return GlassSurface(
        settings: scope?.settings ?? const GlassSettings(),
        radius: radius,
        circle: circle,
        padding: padding,
        width: width,
        height: height,
        child: child,
      );
    }

    Widget content = child ?? const SizedBox.shrink();
    if (padding != null) content = Padding(padding: padding!, child: content);
    Widget shape = _ShapeRenderWidget(
      link: scope.link,
      radius: radius,
      circle: circle,
      child: content,
    );
    if (width != null || height != null) {
      shape = SizedBox(width: width, height: height, child: shape);
    }
    return shape;
  }
}

class _GroupLink {
  _RenderGlassGroup? group;
  final List<_RenderGroupShape> shapes = [];

  void add(_RenderGroupShape shape) {
    shapes.add(shape);
    _repaintGroup();
  }

  void remove(_RenderGroupShape shape) {
    shapes.remove(shape);
    _repaintGroup();
  }

  void _repaintGroup() {
    final g = group;
    if (g != null && g.attached) g.markNeedsPaint();
  }
}

class _GroupScope extends InheritedWidget {
  const _GroupScope({
    required this.link,
    required this.settings,
    required super.child,
  });

  final _GroupLink link;
  final GlassSettings settings;

  @override
  bool updateShouldNotify(_GroupScope oldWidget) =>
      link != oldWidget.link || settings != oldWidget.settings;
}

class _GroupRenderWidget extends SingleChildRenderObjectWidget {
  const _GroupRenderWidget({
    required this.link,
    required this.settings,
    required this.blend,
    required this.edge,
    required this.devicePixelRatio,
    super.child,
  });

  final _GroupLink link;
  final GlassSettings settings;
  final double blend;
  final double edge;
  final double devicePixelRatio;

  @override
  RenderObject createRenderObject(BuildContext context) => _RenderGlassGroup(
    link: link,
    settings: settings,
    blend: blend,
    edge: edge,
    devicePixelRatio: devicePixelRatio,
  );

  @override
  void updateRenderObject(
    BuildContext context,
    _RenderGlassGroup renderObject,
  ) {
    renderObject
      ..settings = settings
      ..blend = blend
      ..edge = edge
      ..devicePixelRatio = devicePixelRatio;
  }
}

class _RenderGlassGroup extends RenderProxyBox {
  _RenderGlassGroup({
    required _GroupLink link,
    required GlassSettings settings,
    required double blend,
    required double edge,
    required double devicePixelRatio,
  }) : _link = link,
       _settings = settings,
       _blend = blend,
       _edge = edge,
       _devicePixelRatio = devicePixelRatio {
    _link.group = this;
  }

  final _GroupLink _link;
  final GlassPass _pass = GlassPass();
  final LayerHandle<ClipPathLayer> _blurClip = LayerHandle();
  final LayerHandle<ClipRectLayer> _shaderClip = LayerHandle();

  GlassSettings _settings;
  set settings(GlassSettings v) {
    if (v == _settings) return;
    _settings = v;
    markNeedsPaint();
  }

  double _blend;
  set blend(double v) {
    if (v == _blend) return;
    _blend = v;
    markNeedsPaint();
  }

  double _edge;
  set edge(double v) {
    if (v == _edge) return;
    _edge = v;
    markNeedsPaint();
  }

  double _devicePixelRatio;
  set devicePixelRatio(double v) {
    if (v == _devicePixelRatio) return;
    _devicePixelRatio = v;
    markNeedsPaint();
  }

  @override
  bool get alwaysNeedsCompositing => true;

  @override
  void paint(PaintingContext context, Offset offset) {
    final shapes = _link.shapes
        .where((s) => s.attached && s.hasSize && !s.size.isEmpty)
        .take(GlassPass.maxShapes)
        .toList();
    if (!_pass.available || shapes.isEmpty) {
      super.paint(context, offset);
      return;
    }

    final local = <RRect>[];
    final screen = <GlassShapeRect>[];
    Rect? union;
    for (final s in shapes) {
      final rect = MatrixUtils.transformRect(
        s.getTransformTo(this),
        Offset.zero & s.size,
      );
      final onScreen = screenRectOf(s);
      final shapeScale = onScreen.width / s.size.width;
      final radius = s.cornerRadius;
      local.add(
        RRect.fromRectAndRadius(
          rect,
          Radius.circular(radius * rect.width / s.size.width),
        ),
      );
      screen.add(GlassShapeRect(onScreen, radius * shapeScale));
      union = union == null ? rect : union.expandToInclude(rect);
    }

    final shapesBounds = union!;
    final clipRect = shapesBounds.inflate(_blend + (_edge > 0 ? 20 : 2));
    final toScreen = getTransformTo(null);
    final screenBounds = MatrixUtils.transformRect(toScreen, clipRect);
    final scale = screenBounds.width / clipRect.width;

    _pass.configure(
      shapes: screen,
      bounds: screenBounds,
      settings: _settings,
      devicePixelRatio: _devicePixelRatio,
      blend: _blend,
      edge: _edge,
      scale: scale,
    );

    final blur =
        _settings.blur * _settings.visibility.clamp(0.0, 1.0).toDouble();
    if (blur > 0.01) {
      final path = Path();
      for (final r in local) {
        path.addRRect(r);
      }
      _blurClip.layer = context.pushClipPath(
        needsCompositing,
        offset,
        shapesBounds,
        path,
        (context, offset) =>
            context.pushLayer(_pass.blurLayer(blur), (c, o) {}, offset),
        oldLayer: _blurClip.layer,
      );
    } else {
      _blurClip.layer = null;
    }

    _shaderClip.layer = context.pushClipRect(
      needsCompositing,
      offset,
      clipRect,
      (context, offset) =>
          context.pushLayer(_pass.shaderLayer(), (c, o) {}, offset),
      oldLayer: _shaderClip.layer,
    );

    super.paint(context, offset);
  }

  @override
  void dispose() {
    if (_link.group == this) _link.group = null;
    _blurClip.layer = null;
    _shaderClip.layer = null;
    _pass.dispose();
    super.dispose();
  }
}

class _ShapeRenderWidget extends SingleChildRenderObjectWidget {
  const _ShapeRenderWidget({
    required this.link,
    required this.radius,
    required this.circle,
    super.child,
  });

  final _GroupLink link;
  final double radius;
  final bool circle;

  @override
  RenderObject createRenderObject(BuildContext context) =>
      _RenderGroupShape(link: link, radius: radius, circle: circle);

  @override
  void updateRenderObject(
    BuildContext context,
    _RenderGroupShape renderObject,
  ) {
    renderObject
      ..link = link
      ..radius = radius
      ..circle = circle;
  }
}

class _RenderGroupShape extends RenderProxyBox {
  _RenderGroupShape({
    required _GroupLink link,
    required double radius,
    required bool circle,
  }) : _link = link,
       _radius = radius,
       _circle = circle;

  final LayerHandle<TransformWatchLayer> _watch = LayerHandle();

  _GroupLink _link;
  set link(_GroupLink v) {
    if (v == _link) return;
    if (attached) _link.remove(this);
    _link = v;
    if (attached) _link.add(this);
  }

  double _radius;
  set radius(double v) {
    if (v == _radius) return;
    _radius = v;
    _link._repaintGroup();
  }

  bool _circle;
  set circle(bool v) {
    if (v == _circle) return;
    _circle = v;
    _link._repaintGroup();
  }

  double get cornerRadius {
    final max = size.shortestSide / 2;
    return _circle ? max : math.min(_radius, max);
  }

  @override
  bool get alwaysNeedsCompositing => true;

  @override
  void attach(PipelineOwner owner) {
    super.attach(owner);
    _link.add(this);
  }

  @override
  void detach() {
    _link.remove(this);
    super.detach();
  }

  @override
  void performLayout() {
    super.performLayout();
    _link._repaintGroup();
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    final watch = _watch.layer ??= TransformWatchLayer();
    watch
      ..target = this
      ..lastRect = hasSize ? screenRectOf(this) : null
      ..onChanged = _link._repaintGroup;
    context.pushLayer(watch, (context, offset) {}, offset);
    super.paint(context, offset);
  }

  @override
  void dispose() {
    _watch.layer = null;
    super.dispose();
  }
}
