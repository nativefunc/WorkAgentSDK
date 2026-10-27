import 'package:flutter/material.dart';

import '../../../glass/glass_presets.dart';
import '../../../glass/glass_sheet.dart';
import '../../../glass/glass_surface.dart';
import '../../../glass/glass_toast.dart';
import '../../../glass/pressable.dart';
import '../../../models/chat_models.dart';
import '../../../state/auth_store.dart';
import '../../../state/chat_store.dart';
import '../../../theme/app_theme.dart';
import '../../../utils/time_format.dart';
import '../../../utils/route_guard.dart';

Future<void> showSessionPanel(BuildContext context) async {
  await singleFlight<void>('sessions', () => _showSessionPanel(context));
}

Future<void> _showSessionPanel(BuildContext context) {
  return Navigator.of(context, rootNavigator: true).push(
    PageRouteBuilder<void>(
      opaque: false,
      transitionDuration: const Duration(milliseconds: 340),
      reverseTransitionDuration: const Duration(milliseconds: 260),
      pageBuilder: (context, animation, secondaryAnimation) =>
          const SessionPanel(),
      transitionsBuilder: (context, animation, secondaryAnimation, child) {
        return SlideTransition(
          position: Tween<Offset>(begin: const Offset(-1, 0), end: Offset.zero)
              .animate(
                CurvedAnimation(
                  parent: animation,
                  curve: Curves.easeOutCubic,
                  reverseCurve: Curves.easeInCubic,
                ),
              ),
          child: child,
        );
      },
    ),
  );
}

class SessionPanel extends StatefulWidget {
  const SessionPanel({super.key});

  @override
  State<SessionPanel> createState() => _SessionPanelState();
}

class _SessionPanelState extends State<SessionPanel> {
  double _dragOffset = 0;
  bool _dragging = false;

  void _close() => popRoute(context);

  void _onDragUpdate(DragUpdateDetails d) {
    setState(() {
      _dragging = true;
      _dragOffset = (_dragOffset + d.delta.dx).clamp(
        double.negativeInfinity,
        0.0,
      );
    });
  }

  void _onDragEnd(DragEndDetails d) {
    final width = MediaQuery.sizeOf(context).width;
    final velocity = d.primaryVelocity ?? 0;
    if (_dragOffset < -width * 0.3 || velocity < -600) {
      _close();
      return;
    }
    setState(() {
      _dragging = false;
      _dragOffset = 0;
    });
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;

    return GestureDetector(
      onHorizontalDragUpdate: _onDragUpdate,
      onHorizontalDragEnd: _onDragEnd,
      child: AnimatedSlide(
        offset: Offset(width == 0 ? 0 : _dragOffset / width, 0),
        duration: _dragging ? Duration.zero : const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
        child: Material(
          color: AppColors.canvas,
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(
                maxWidth: AppLayout.listWidth + 32,
              ),
              child: SessionBrowser(
                onOpen: (s) {
                  ChatScope.read(context).select(s.id);
                  _close();
                },
                onNewChat: () {
                  ChatScope.read(context).startNewSession();
                  _close();
                },
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class SessionBrowser extends StatefulWidget {
  const SessionBrowser({
    super.key,
    required this.onOpen,
    required this.onNewChat,
    this.embedded = false,
    this.bottomInset,
  });

  final ValueChanged<ChatSession> onOpen;
  final VoidCallback onNewChat;

  final bool embedded;

  final double? bottomInset;

  @override
  State<SessionBrowser> createState() => _SessionBrowserState();
}

class _SessionBrowserState extends State<SessionBrowser> {
  final TextEditingController _search = TextEditingController();
  bool _searching = false;
  String _query = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _toggleSearch() {
    setState(() {
      _searching = !_searching;
      if (!_searching) {
        _search.clear();
        _query = '';
      }
    });
  }

  void _showActions(ChatSession session) {
    final store = ChatScope.read(context);
    showGlassSheet<void>(
      context,
      builder: (sheetContext) => _SessionActions(
        session: session,
        onDelete: () async {
          if (!isTopRoute(sheetContext)) return;
          popRoute(sheetContext);
          try {
            await store.delete(session.id);
            if (mounted) {
              showGlassToast(
                context,
                'Chat deleted',
                icon: Icons.delete_outline_rounded,
              );
            }
          } catch (error) {
            if (mounted) {
              showGlassToast(
                context,
                error.toString(),
                icon: Icons.error_outline_rounded,
              );
            }
          }
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final store = ChatScope.of(context);
    final now = DateTime.now();
    final bottomSafe = MediaQuery.paddingOf(context).bottom;
    final bottom = widget.bottomInset ?? bottomSafe + 110;

    final query = _query.trim().toLowerCase();
    final sessions = store.history
        .where((s) => query.isEmpty || s.title.toLowerCase().contains(query))
        .toList();

    return Stack(
      children: [
        SafeArea(
          bottom: false,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _Header(
                onSearch: _toggleSearch,
                searching: _searching,
                compact: widget.embedded,
              ),
              if (_searching)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: _SearchField(
                    controller: _search,
                    onChanged: (v) => setState(() => _query = v),
                  ),
                ),
              Expanded(
                child: ListView(
                  keyboardDismissBehavior:
                      ScrollViewKeyboardDismissBehavior.onDrag,
                  padding: EdgeInsets.fromLTRB(
                    widget.embedded ? 10 : 16,
                    8,
                    widget.embedded ? 10 : 16,
                    bottom,
                  ),
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(14, 8, 14, 10),
                      child: Text(
                        'Recents',
                        style: TextStyle(
                          fontSize: widget.embedded ? 15 : 19,
                          fontWeight: FontWeight.w700,
                          color: widget.embedded
                              ? AppColors.inkSecondary
                              : AppColors.ink,
                        ),
                      ),
                    ),
                    if (sessions.isEmpty)
                      Padding(
                        padding: const EdgeInsets.all(14),
                        child: Text(
                          query.isEmpty
                              ? 'Your chats will show up here.'
                              : 'No chats match “${_query.trim()}”.',
                          style: const TextStyle(
                            fontSize: 15,
                            color: AppColors.inkSecondary,
                          ),
                        ),
                      )
                    else
                      for (final s in sessions)
                        _SessionRow(
                          session: s,
                          selected: s.id == store.current.id,
                          compact: widget.embedded,
                          stamp: TimeFormat.sessionStamp(s.updatedAt, now),
                          onTap: () => widget.onOpen(s),
                          onLongPress: () => _showActions(s),
                        ),
                  ],
                ),
              ),
            ],
          ),
        ),
        if (!widget.embedded)
          Positioned(
            right: 20,
            bottom: bottomSafe + 20,
            child: _NewChatButton(onTap: widget.onNewChat),
          ),
      ],
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.onSearch,
    required this.searching,
    this.compact = false,
  });

  final VoidCallback onSearch;
  final bool searching;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: compact
          ? const EdgeInsets.fromLTRB(24, 12, 12, 8)
          : const EdgeInsets.fromLTRB(30, 20, 16, 16),
      child: Row(
        children: [
          Expanded(
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(
                AppInfo.name,
                maxLines: 1,
                style: TextStyle(
                  fontSize: compact ? 24 : 30,
                  fontWeight: FontWeight.w700,
                  letterSpacing: -0.6,
                  color: AppColors.ink,
                ),
              ),
            ),
          ),
          const SizedBox(width: 12),
          GlassSurface(
            settings: GlassPresets.control,
            radius: 26,
            height: 52,
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Pressable(
                  onTap: onSearch,
                  semanticLabel: searching ? 'Close search' : 'Search chats',
                  pressedScale: 0.88,
                  child: SizedBox.square(
                    dimension: 40,
                    child: Icon(
                      searching ? Icons.close_rounded : Icons.search_rounded,
                      size: 26,
                      color: AppColors.ink,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                CircleAvatar(
                  radius: 20,
                  backgroundColor: const Color(0xFF5BBF9A),
                  child: Text(
                    AuthScope.of(context).account?.initials ?? '',
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _SearchField extends StatelessWidget {
  const _SearchField({required this.controller, required this.onChanged});

  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 44,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.search_rounded,
            size: 20,
            color: AppColors.inkSecondary,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: controller,
              onChanged: onChanged,
              autofocus: true,
              textInputAction: TextInputAction.search,
              style: const TextStyle(fontSize: 16, color: AppColors.ink),
              decoration: const InputDecoration.collapsed(
                hintText: 'Search chats',
                hintStyle: TextStyle(color: AppColors.inkTertiary),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SessionRow extends StatelessWidget {
  const _SessionRow({
    required this.session,
    required this.selected,
    required this.stamp,
    required this.onTap,
    required this.onLongPress,
    this.compact = false,
  });

  final ChatSession session;
  final bool selected;
  final String stamp;
  final VoidCallback onTap;

  final VoidCallback onLongPress;

  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      onLongPress: onLongPress,
      semanticLabel: '${session.title}, $stamp',
      pressedScale: 0.98,
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: 14,
          vertical: compact ? 11 : 14,
        ),
        decoration: BoxDecoration(
          color: selected
              ? (compact ? const Color(0x0F000000) : AppColors.surface)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                session.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: compact ? 15.5 : 17,
                  color: AppColors.ink,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Text(
              stamp,
              style: const TextStyle(
                fontSize: 13,
                color: AppColors.inkTertiary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NewChatButton extends StatelessWidget {
  const _NewChatButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: 'New chat',
      pressedScale: 0.94,
      child: Container(
        height: 56,
        padding: const EdgeInsets.symmetric(horizontal: 22),
        decoration: const ShapeDecoration(
          color: AppColors.ink,
          shape: StadiumBorder(),
          shadows: [
            BoxShadow(
              color: Color(0x33000000),
              blurRadius: 18,
              offset: Offset(0, 8),
            ),
          ],
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.edit_outlined, size: 22, color: Colors.white),
            SizedBox(width: 10),
            Text(
              'Chat',
              style: TextStyle(
                fontSize: 17,
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

class _SessionActions extends StatelessWidget {
  const _SessionActions({required this.session, required this.onDelete});

  final ChatSession session;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 0, 4, 14),
          child: Text(
            session.title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w700,
              color: AppColors.ink,
            ),
          ),
        ),
        _SheetAction(
          icon: Icons.delete_outline_rounded,
          label: 'Delete',
          color: AppColors.danger,
          onTap: onDelete,
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
