import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../glass/glass_controls.dart';
import '../../glass/glass_presets.dart';
import '../../glass/glass_sheet.dart';
import '../../glass/glass_surface.dart';
import '../../glass/glass_toast.dart';
import '../../glass/pressable.dart';
import '../../models/chat_models.dart';
import '../../state/chat_store.dart';
import '../../state/cloud_connections.dart';
import '../../theme/app_theme.dart';
import '../../utils/route_guard.dart';

Future<void> showTakeControl(
  BuildContext context,
  CloudConnection connection, {
  String? chatId,
  ChatRequest? request,
}) async {
  await singleFlight<void>(
    'take-control',
    () => Navigator.of(context, rootNavigator: true).push(
      MaterialPageRoute<void>(
        fullscreenDialog: true,
        builder: (_) => TakeControlPage(
          connection: connection,
          chatId: chatId,
          request: request,
        ),
      ),
    ),
  );
}

@immutable
class _FrameMeta {
  const _FrameMeta({
    required this.width,
    required this.height,
    required this.coordWidth,
    required this.coordHeight,
    this.url,
    this.title,
  });

  factory _FrameMeta.fromJson(Map<String, dynamic> json) => _FrameMeta(
    width: (json['width'] as num).toDouble(),
    height: (json['height'] as num).toDouble(),
    coordWidth: (json['coord_width'] as num).toDouble(),
    coordHeight: (json['coord_height'] as num).toDouble(),
    url: json['url'] as String?,
    title: json['title'] as String?,
  );

  final double width;
  final double height;
  final double coordWidth;
  final double coordHeight;
  final String? url;
  final String? title;
}

enum _Link { connecting, live, closed }

class TakeControlPage extends StatefulWidget {
  const TakeControlPage({
    super.key,
    required this.connection,
    this.chatId,
    this.request,
  });

  final CloudConnection connection;
  final String? chatId;
  final ChatRequest? request;

  @override
  State<TakeControlPage> createState() => _TakeControlPageState();
}

class _TakeControlPageState extends State<TakeControlPage> {
  static const Color _backdrop = Color(0xFF0E0E11);

  final TransformationController _zoom = TransformationController();
  final TextEditingController _typing = TextEditingController();
  final FocusNode _keyboardFocus = FocusNode();

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _ping;

  _Link _link = _Link.connecting;
  String? _closedReason;
  bool _finished = false;

  Uint8List? _frame;
  _FrameMeta? _meta;

  Offset _cursor = const Offset(0.5, 0.5);
  bool _showCursor = false;

  int _clicks = 0;

  double _scrollRemainder = 0;
  Offset _scrollAt = Offset.zero;

  String _sentText = '';

  final Set<String> _modifiers = {};

  String? _sentKey;
  int _sentKeyCount = 0;

  bool _typingOpen = false;

  bool get _isBrowser => widget.connection.kind == CloudKind.browser;
  String get _what => _isBrowser ? 'Browser' : 'Your computer';

  @override
  void initState() {
    super.initState();
    _keyboardFocus.addListener(_onFocusChange);
    _connect();
  }

  @override
  void dispose() {
    _disconnect();
    _keyboardFocus.removeListener(_onFocusChange);
    _zoom.dispose();
    _typing.dispose();
    _keyboardFocus.dispose();
    super.dispose();
  }

  void _connect() {
    _disconnect();
    final api = ChatScope.read(context).api;
    final uri = api.controlUri(
      target: _isBrowser ? 'browser' : 'computer',
      chatId: widget.chatId,
      requestId: widget.request?.id,
    );
    setState(() {
      _link = _Link.connecting;
      _closedReason = null;
    });
    final channel = WebSocketChannel.connect(uri);
    _channel = channel;
    _subscription = channel.stream.listen(
      _onMessage,
      onError: (Object _) => _onClosed(null),
      onDone: () => _onClosed(_closeReason(channel.closeCode)),
    );
    _ping = Timer.periodic(
      const Duration(seconds: 20),
      (_) => _send({'type': 'ping'}),
    );
  }

  String? _closeReason(int? code) => switch (code) {
    4401 => 'Please sign in again',
    4404 => 'This chat no longer exists',
    4409 => 'This request was already handled',
    _ => null,
  };

  void _disconnect() {
    _ping?.cancel();
    _ping = null;
    _subscription?.cancel();
    _subscription = null;
    _channel?.sink.close();
    _channel = null;
  }

  void _onMessage(dynamic message) {
    if (!mounted) return;
    if (message is List<int>) {
      setState(() {
        _frame = message is Uint8List ? message : Uint8List.fromList(message);
        _link = _Link.live;
      });
      return;
    }
    if (message is! String) return;
    final data = jsonDecode(message);
    if (data is! Map) return;
    switch (data['type']) {
      case 'frame':
        setState(
          () => _meta = _FrameMeta.fromJson(data.cast<String, dynamic>()),
        );
      case 'error':
        showGlassToast(
          context,
          (data['message'] as String?) ?? "That didn't work",
          icon: Icons.block_rounded,
        );
      case 'closed':
        _closedReason = data['reason'] as String?;
    }
  }

  void _onClosed(String? reason) {
    if (!mounted || _finished) return;
    _ping?.cancel();
    setState(() {
      _link = _Link.closed;
      _closedReason ??= reason;
    });
  }

  void _send(Map<String, Object?> message) {
    if (_link == _Link.closed) return;
    _channel?.sink.add(jsonEncode(message));
  }

  void _input(String action, [Map<String, Object?> args = const {}]) {
    _send({'type': 'input', 'action': action, ...args});
  }

  void _handBack() {
    _finished = true;
    _send({'type': 'done'});
    Future<void>.delayed(const Duration(milliseconds: 150), _disconnect);
    showGlassToast(
      context,
      widget.request != null
          ? '${AppInfo.name} is continuing'
          : 'Back to ${AppInfo.name}',
      icon: Icons.check_rounded,
    );
    popRoute(context);
  }

  Offset? _remotePoint(Offset local, Size size) {
    final meta = _meta;
    if (meta == null || size.isEmpty) return null;
    final fx = (local.dx / size.width).clamp(0.0, 1.0);
    final fy = (local.dy / size.height).clamp(0.0, 1.0);
    return Offset(fx * meta.coordWidth, fy * meta.coordHeight);
  }

  void _click(String action, Offset local, Size size) {
    final point = _remotePoint(local, size);
    if (point == null) return;
    HapticFeedback.selectionClick();
    setState(() {
      _cursor = Offset(
        (local.dx / size.width).clamp(0.0, 1.0),
        (local.dy / size.height).clamp(0.0, 1.0),
      );
      _showCursor = true;
      _clicks++;
    });
    _input(action, {'x': point.dx.round(), 'y': point.dy.round()});
  }

  bool get _zoomed => _zoom.value.getMaxScaleOnAxis() > 1.01;

  void _onInteractionStart(ScaleStartDetails details, Size size) {
    _scrollRemainder = 0;
    _scrollAt = _toChild(details.localFocalPoint);
  }

  void _onInteractionUpdate(ScaleUpdateDetails details, Size size) {
    if (_zoomed || details.pointerCount != 1) return;
    _scrollRemainder += details.focalPointDelta.dy;
    const step = 36.0;
    while (_scrollRemainder.abs() >= step) {
      final down = _scrollRemainder < 0;
      _scrollRemainder += down ? step : -step;
      final point = _remotePoint(_scrollAt, size);
      if (point == null) return;
      _input('scroll', {
        'x': point.dx.round(),
        'y': point.dy.round(),
        'direction': down ? 'down' : 'up',
        'amount': 1,
      });
    }
  }

  Offset _toChild(Offset viewport) => _zoom.toScene(viewport);

  void _onFocusChange() {
    if (!_keyboardFocus.hasFocus && _typingOpen) {
      setState(() => _typingOpen = false);
    }
  }

  void _toggleKeyboard() {
    if (_typingOpen) {
      _closeKeyboard();
      return;
    }
    _typing.clear();
    _sentText = '';
    setState(() => _typingOpen = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _typingOpen) _keyboardFocus.requestFocus();
    });
  }

  void _closeKeyboard() {
    setState(() => _typingOpen = false);
    _keyboardFocus.unfocus();
  }

  void _onTyped(String value) {
    final before = _sentText;
    _sentText = value;
    if (value.startsWith(before)) {
      final added = value.substring(before.length);
      if (added.isEmpty) return;
      if (_modifiers.isNotEmpty) {
        _sendKeyName(added.characters.first.toLowerCase());
        _typing.value = TextEditingValue(
          text: before,
          selection: TextSelection.collapsed(offset: before.length),
        );
        _sentText = before;
        return;
      }
      _input('type', {'text': added});
    } else if (before.startsWith(value)) {
      for (var i = 0; i < before.length - value.length; i++) {
        _input('key', {'text': 'backspace'});
      }
    } else {
      for (var i = 0; i < before.length; i++) {
        _input('key', {'text': 'backspace'});
      }
      if (value.isNotEmpty) _input('type', {'text': value});
    }
  }

  void _onKey(String label) {
    HapticFeedback.selectionClick();
    final modifier = _Keys.modifiers[label];
    if (modifier != null) {
      setState(() {
        if (!_modifiers.remove(modifier)) _modifiers.add(modifier);
      });
      return;
    }
    final name = _Keys.names[label];
    if (name == null) return;
    if (name == 'enter') {
      _typing.clear();
      _sentText = '';
    }
    _sendKeyName(name);
    setState(() {
      _sentKey = label;
      _sentKeyCount++;
    });
  }

  void _sendKeyName(String key) {
    final combo = [..._modifiers, key].join('+');
    _input('key', {'text': combo});
    if (_modifiers.isNotEmpty) setState(_modifiers.clear);
  }

  String _liveSubtitle(_FrameMeta? meta) {
    final url = meta?.url;
    final host = _isBrowser && url != null ? Uri.tryParse(url)?.host : null;
    return host == null || host.isEmpty ? "You're in control" : host;
  }

  void _navigate(String url) => _input('navigate', {'url': url});

  Future<void> _editAddress() async {
    final target = await showGlassSheet<String>(
      context,
      builder: (sheetContext) => _AddressSheet(initial: _meta?.url ?? ''),
    );
    final value = target?.trim();
    if (value != null && value.isNotEmpty) _navigate(value);
  }

  @override
  Widget build(BuildContext context) {
    final padding = MediaQuery.paddingOf(context);
    final keyboard = MediaQuery.viewInsetsOf(context).bottom;
    final typing = _typingOpen;
    final meta = _meta;
    final frame = _frame;
    final aspect = meta == null || meta.height == 0
        ? 16 / 10
        : meta.width / meta.height;

    return Scaffold(
      backgroundColor: _backdrop,
      resizeToAvoidBottomInset: false,
      body: Stack(
        children: [
          Positioned.fill(
            child: Padding(
              padding: EdgeInsets.fromLTRB(
                12,
                padding.top + 70,
                12,
                typing
                    ? keyboard + _TypingBar.height + 24
                    : padding.bottom + 90,
              ),
              child: Center(
                child: AspectRatio(
                  aspectRatio: aspect,
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final size = constraints.biggest;
                      return InteractiveViewer(
                        transformationController: _zoom,
                        minScale: 1,
                        maxScale: 4,
                        panEnabled: _zoomed,
                        onInteractionStart: (d) => _onInteractionStart(d, size),
                        onInteractionUpdate: (d) =>
                            _onInteractionUpdate(d, size),
                        onInteractionEnd: (_) => setState(() {}),
                        child: _RemoteScreen(
                          frame: frame,
                          cursor: _cursor,
                          showCursor: _showCursor,
                          clicks: _clicks,
                          onTap: (local) => _click('left_click', local, size),
                          onDoubleTap: (local) =>
                              _click('double_click', local, size),
                          onLongPress: (local) =>
                              _click('right_click', local, size),
                        ),
                      );
                    },
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
                  icon: Icons.close_rounded,
                  semanticLabel: 'Done, let ${AppInfo.name} continue',
                  settings: GlassPresets.darkControl,
                  iconColor: Colors.white,
                  onTap: _handBack,
                ),
                Expanded(
                  child: _Title(
                    title: _isBrowser
                        ? (meta?.title?.isNotEmpty == true
                              ? meta!.title!
                              : _what)
                        : _what,
                    subtitle: switch (_link) {
                      _Link.connecting => 'Connecting…',
                      _Link.live => _liveSubtitle(meta),
                      _Link.closed => 'Disconnected',
                    },
                    live: _link == _Link.live,
                  ),
                ),
                GlassCircleButton(
                  icon: typing
                      ? Icons.keyboard_hide_outlined
                      : Icons.keyboard_outlined,
                  semanticLabel: typing ? 'Hide keyboard' : 'Keyboard',
                  settings: GlassPresets.darkControl,
                  iconColor: Colors.white,
                  onTap: _toggleKeyboard,
                ),
              ],
            ),
          ),

          if (!typing)
            Positioned(
              left: 16,
              right: 16,
              bottom: padding.bottom + 16,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (_isBrowser)
                    GlassSurface(
                      settings: GlassPresets.darkControl,
                      radius: 22,
                      height: 44,
                      padding: const EdgeInsets.symmetric(horizontal: 2),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _CapsuleIcon(
                            icon: Icons.arrow_back_ios_new_rounded,
                            iconSize: 18,
                            semanticLabel: 'Back',
                            onTap: () => _navigate('back'),
                          ),
                          _CapsuleIcon(
                            icon: Icons.refresh_rounded,
                            semanticLabel: 'Reload',
                            onTap: () => _navigate('reload'),
                          ),
                          _CapsuleIcon(
                            icon: Icons.travel_explore_rounded,
                            semanticLabel: 'Go to an address',
                            onTap: _editAddress,
                          ),
                        ],
                      ),
                    ),
                  AnimatedBuilder(
                    animation: _zoom,
                    builder: (context, _) {
                      if (!_zoomed) return const SizedBox.shrink();
                      return Padding(
                        padding: EdgeInsets.only(left: _isBrowser ? 10 : 0),
                        child: _ResetZoom(
                          onTap: () =>
                              setState(() => _zoom.value = Matrix4.identity()),
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),

          if (typing)
            Positioned(
              left: 12,
              right: 12,
              bottom: keyboard + 8,
              child: _TypingBar(
                controller: _typing,
                focusNode: _keyboardFocus,
                onChanged: _onTyped,
                onSubmitted: () => _onKey(_Keys.enter),
                target: _what,
                computerKeys: !_isBrowser,
                armed: _modifiers,
                sentKey: _sentKey,
                sentKeyCount: _sentKeyCount,
                onKey: _onKey,
                onClose: _closeKeyboard,
              ),
            ),

          if (_link == _Link.connecting && frame == null)
            const Positioned.fill(
              child: IgnorePointer(
                child: Center(
                  child: SizedBox(
                    width: 26,
                    height: 26,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.4,
                      color: Colors.white,
                    ),
                  ),
                ),
              ),
            ),

          if (_link == _Link.closed)
            Positioned.fill(
              child: _ConnectionLost(
                what: _what,
                reason: _closedReason,
                onReconnect: _connect,
                onClose: () => popRoute(context),
              ),
            ),
        ],
      ),
    );
  }
}

class _AddressSheet extends StatefulWidget {
  const _AddressSheet({required this.initial});

  final String initial;

  @override
  State<_AddressSheet> createState() => _AddressSheetState();
}

class _AddressSheetState extends State<_AddressSheet> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.initial,
  );

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Go to',
          style: TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w700,
            color: AppColors.ink,
          ),
        ),
        const SizedBox(height: 12),
        Container(
          height: 52,
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(16),
          ),
          alignment: Alignment.centerLeft,
          child: TextField(
            controller: _controller,
            autofocus: true,
            keyboardType: TextInputType.url,
            autocorrect: false,
            textInputAction: TextInputAction.go,
            onSubmitted: (value) => popRoute(context, value),
            style: const TextStyle(fontSize: 16, color: AppColors.ink),
            decoration: const InputDecoration.collapsed(
              hintText: 'Address',
              hintStyle: TextStyle(color: AppColors.inkTertiary),
            ),
          ),
        ),
      ],
    );
  }
}

class _CapsuleIcon extends StatelessWidget {
  const _CapsuleIcon({
    required this.icon,
    required this.semanticLabel,
    required this.onTap,
    this.iconSize = 22,
  });

  final IconData icon;
  final String semanticLabel;
  final VoidCallback onTap;
  final double iconSize;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: semanticLabel,
      pressedScale: 0.86,
      child: SizedBox(
        width: 44,
        height: 44,
        child: Center(
          child: Icon(icon, size: iconSize, color: Colors.white),
        ),
      ),
    );
  }
}

class _Title extends StatelessWidget {
  const _Title({
    required this.title,
    required this.subtitle,
    required this.live,
  });

  final String title;
  final String subtitle;
  final bool live;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10),
      child: Column(
        children: [
          Text(
            title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 2),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                  color: live ? AppColors.success : AppColors.warning,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 12.5, color: Colors.white70),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RemoteScreen extends StatelessWidget {
  const _RemoteScreen({
    required this.frame,
    required this.cursor,
    required this.showCursor,
    required this.clicks,
    required this.onTap,
    required this.onDoubleTap,
    required this.onLongPress,
  });

  final Uint8List? frame;
  final Offset cursor;
  final bool showCursor;
  final int clicks;
  final ValueChanged<Offset> onTap;
  final ValueChanged<Offset> onDoubleTap;
  final ValueChanged<Offset> onLongPress;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = constraints.biggest;
        final at = Offset(cursor.dx * size.width, cursor.dy * size.height);
        Offset? doubleTapAt;

        return GestureDetector(
          onTapUp: (d) => onTap(d.localPosition),
          onDoubleTapDown: (d) => doubleTapAt = d.localPosition,
          onDoubleTap: () {
            final point = doubleTapAt;
            if (point != null) onDoubleTap(point);
          },
          onLongPressStart: (d) => onLongPress(d.localPosition),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Positioned.fill(
                  child: frame == null
                      ? const ColoredBox(color: Color(0xFF1B1B20))
                      : Image.memory(
                          frame!,
                          fit: BoxFit.fill,
                          gaplessPlayback: true,
                        ),
                ),
                if (clicks > 0)
                  Positioned(
                    left: at.dx - 22,
                    top: at.dy - 22,
                    child: IgnorePointer(
                      child: _ClickRipple(key: ValueKey(clicks)),
                    ),
                  ),
                if (showCursor)
                  Positioned(
                    left: at.dx,
                    top: at.dy,
                    child: const IgnorePointer(
                      child: CustomPaint(
                        size: Size(14, 20),
                        painter: _CursorPainter(),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _ClickRipple extends StatelessWidget {
  const _ClickRipple({super.key});

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween<double>(begin: 0, end: 1),
      duration: const Duration(milliseconds: 450),
      curve: Curves.easeOutCubic,
      builder: (context, t, _) => Opacity(
        opacity: 1 - t,
        child: Transform.scale(
          scale: 0.3 + t * 0.7,
          child: Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: const Color(0x335B5BF0),
              border: Border.all(color: AppColors.accent, width: 2),
            ),
          ),
        ),
      ),
    );
  }
}

class _CursorPainter extends CustomPainter {
  const _CursorPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..moveTo(0, 0)
      ..lineTo(0, size.height * 0.85)
      ..lineTo(size.width * 0.32, size.height * 0.64)
      ..lineTo(size.width * 0.55, size.height)
      ..lineTo(size.width * 0.72, size.height * 0.92)
      ..lineTo(size.width * 0.5, size.height * 0.58)
      ..lineTo(size.width, size.height * 0.58)
      ..close();
    canvas.drawPath(path, Paint()..color = Colors.black);
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.4
        ..color = Colors.white,
    );
  }

  @override
  bool shouldRepaint(_CursorPainter oldDelegate) => false;
}

class _ConnectionLost extends StatelessWidget {
  const _ConnectionLost({
    required this.what,
    required this.onReconnect,
    required this.onClose,
    this.reason,
  });

  final String what;
  final String? reason;
  final VoidCallback onReconnect;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: const Color(0xE60E0E11),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.link_off_rounded, size: 40, color: Colors.white),
              const SizedBox(height: 14),
              Text(
                reason ?? '$what disconnected',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 18),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _OutlineButton(label: 'Close', onTap: onClose),
                  const SizedBox(width: 10),
                  _OutlineButton(
                    label: 'Reconnect',
                    onTap: onReconnect,
                    filled: true,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _OutlineButton extends StatelessWidget {
  const _OutlineButton({
    required this.label,
    required this.onTap,
    this.filled = false,
  });

  final String label;
  final VoidCallback onTap;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.95,
      child: Container(
        height: 44,
        padding: const EdgeInsets.symmetric(horizontal: 20),
        alignment: Alignment.center,
        decoration: ShapeDecoration(
          color: filled ? Colors.white : Colors.transparent,
          shape: StadiumBorder(
            side: BorderSide(color: filled ? Colors.white : Colors.white54),
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w600,
            color: filled ? AppColors.ink : Colors.white,
          ),
        ),
      ),
    );
  }
}

abstract final class _Keys {
  static const String esc = 'Esc';
  static const String tab = 'Tab';
  static const String ctrl = 'Ctrl';
  static const String alt = 'Alt';
  static const String cmd = '⌘';
  static const String left = '←';
  static const String up = '↑';
  static const String down = '↓';
  static const String right = '→';
  static const String backspace = '⌫';
  static const String enter = 'Enter';

  static const Map<String, String> names = {
    esc: 'escape',
    tab: 'tab',
    left: 'left',
    up: 'up',
    down: 'down',
    right: 'right',
    backspace: 'backspace',
    enter: 'enter',
  };

  static const Map<String, String> modifiers = {
    ctrl: 'ctrl',
    alt: 'alt',
    cmd: 'cmd',
  };
}

class _TypingBar extends StatelessWidget {
  const _TypingBar({
    required this.controller,
    required this.focusNode,
    required this.onChanged,
    required this.onSubmitted,
    required this.target,
    required this.computerKeys,
    required this.armed,
    required this.sentKey,
    required this.sentKeyCount,
    required this.onKey,
    required this.onClose,
  });

  static const double height = 100;

  final TextEditingController controller;
  final FocusNode focusNode;
  final ValueChanged<String> onChanged;
  final VoidCallback onSubmitted;

  final String target;

  final bool computerKeys;

  final Set<String> armed;

  final String? sentKey;
  final int sentKeyCount;
  final ValueChanged<String> onKey;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final keys = [
      _Keys.esc,
      _Keys.tab,
      _Keys.ctrl,
      _Keys.alt,
      if (computerKeys) _Keys.cmd,
      _Keys.left,
      _Keys.up,
      _Keys.down,
      _Keys.right,
      _Keys.backspace,
      _Keys.enter,
    ];

    return GlassSurface(
      settings: GlassPresets.darkControl,
      radius: 24,
      height: height,
      padding: const EdgeInsets.fromLTRB(16, 8, 8, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            height: 36,
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: controller,
                    focusNode: focusNode,
                    autocorrect: false,
                    enableSuggestions: false,
                    textInputAction: TextInputAction.go,
                    keyboardAppearance: Brightness.dark,
                    cursorColor: Colors.white,
                    style: const TextStyle(fontSize: 15, color: Colors.white),
                    decoration: InputDecoration.collapsed(
                      hintText: 'Typing to $target…',
                      hintStyle: const TextStyle(
                        fontSize: 15,
                        color: Colors.white54,
                      ),
                    ),
                    onChanged: onChanged,
                    onEditingComplete: () {},
                    onSubmitted: (_) => onSubmitted(),
                  ),
                ),
                if (sentKey != null)
                  TweenAnimationBuilder<double>(
                    key: ValueKey(sentKeyCount),
                    tween: Tween(begin: 1, end: 0),
                    duration: const Duration(milliseconds: 900),
                    builder: (context, t, child) =>
                        Opacity(opacity: t, child: child),
                    child: Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: Text(
                        '$sentKey sent',
                        style: const TextStyle(
                          fontSize: 12,
                          color: Colors.white60,
                        ),
                      ),
                    ),
                  ),
                Pressable(
                  onTap: onClose,
                  semanticLabel: 'Hide keyboard',
                  pressedScale: 0.85,
                  child: const SizedBox(
                    width: 40,
                    height: 36,
                    child: Icon(
                      Icons.keyboard_hide_outlined,
                      size: 22,
                      color: Colors.white,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.only(right: 8),
              itemCount: keys.length,
              separatorBuilder: (_, __) => const SizedBox(width: 6),
              itemBuilder: (context, i) => _KeyCap(
                label: keys[i],
                wide: keys[i] == _Keys.enter,
                active: armed.contains(_Keys.modifiers[keys[i]]),
                onTap: () => onKey(keys[i]),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _KeyCap extends StatelessWidget {
  const _KeyCap({
    required this.label,
    required this.onTap,
    this.wide = false,
    this.active = false,
  });

  final String label;
  final VoidCallback onTap;
  final bool wide;

  final bool active;

  @override
  Widget build(BuildContext context) {
    final light = wide || active;
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.9,
      child: Container(
        constraints: BoxConstraints(minWidth: wide ? 64 : 40),
        padding: const EdgeInsets.symmetric(horizontal: 10),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: light ? Colors.white : const Color(0x26FFFFFF),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: light ? AppColors.ink : Colors.white,
          ),
        ),
      ),
    );
  }
}

class _ResetZoom extends StatelessWidget {
  const _ResetZoom({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: 'Reset zoom',
      pressedScale: 0.94,
      child: const GlassSurface(
        settings: GlassPresets.darkControl,
        radius: 22,
        height: 44,
        padding: EdgeInsets.symmetric(horizontal: 16),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.zoom_out_rounded, size: 20, color: Colors.white),
            SizedBox(width: 6),
            Text(
              'Reset zoom',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
