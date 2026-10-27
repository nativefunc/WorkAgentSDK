import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../glass/glass_controls.dart';
import '../../../glass/glass_presets.dart';
import '../../../glass/glass_toast.dart';
import '../../../glass/pressable.dart';
import '../../../models/chat_models.dart';
import '../../../state/chat_store.dart';
import '../../../theme/app_theme.dart';
import '../../../utils/time_format.dart';
import '../../../widgets/markdown_text.dart';
import '../../../utils/route_guard.dart';

class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.message,
    required this.showTime,
    required this.now,
    required this.columnWidth,
    this.sending = false,
    this.error,
    this.onRetry,
    this.onDiscard,
  });

  final ChatMessage message;

  final double columnWidth;

  final bool showTime;
  final DateTime now;

  final bool sending;

  final String? error;
  final VoidCallback? onRetry;
  final VoidCallback? onDiscard;

  static const Radius _round = Radius.circular(22);
  static const Radius _tail = Radius.circular(6);

  @override
  Widget build(BuildContext context) {
    final isUser = message.isUser;
    final maxWidth = columnWidth * (isUser ? 0.8 : 0.92);
    final hasText = message.text.trim().isNotEmpty;

    final bubble = Container(
      constraints: BoxConstraints(maxWidth: maxWidth),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: isUser ? AppColors.ink : AppColors.bubble,
        borderRadius: BorderRadius.only(
          topLeft: _round,
          topRight: _round,
          bottomLeft: isUser ? _round : _tail,
          bottomRight: isUser ? _tail : _round,
        ),
      ),
      child: isUser
          ? SelectableText(
              message.text,
              style: const TextStyle(
                fontSize: 15.5,
                height: 1.42,
                color: Colors.white,
              ),
            )
          : MarkdownText(message.text),
    );

    final caption = error != null
        ? _ErrorCaption(message: error!, onRetry: onRetry, onDiscard: onDiscard)
        : sending
        ? const _Caption('Sending…')
        : showTime
        ? _Caption(TimeFormat.messageStamp(message.sentAt, now))
        : null;

    return Padding(
      padding: EdgeInsets.only(bottom: caption != null ? 14 : 6),
      child: Opacity(
        opacity: sending ? 0.7 : 1,
        child: Column(
          crossAxisAlignment: isUser
              ? CrossAxisAlignment.end
              : CrossAxisAlignment.start,
          children: [
            if (message.images.isNotEmpty)
              Padding(
                padding: EdgeInsets.only(
                  bottom: hasText || message.files.isNotEmpty ? 6 : 0,
                ),
                child: _ImageStrip(images: message.images, maxWidth: maxWidth),
              ),
            for (final file in message.files)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: _FileCard(file: file, width: math.min(maxWidth, 280)),
              ),
            if (hasText) bubble,
            if (caption != null)
              Padding(
                padding: const EdgeInsets.only(top: 5, left: 6, right: 6),
                child: caption,
              ),
          ],
        ),
      ),
    );
  }
}

class _FileCard extends StatelessWidget {
  const _FileCard({required this.file, required this.width});

  final ChatFile file;
  final double width;

  Future<void> _open(BuildContext context) async {
    final id = file.uploadId;
    if (id == null) return;
    final url = ChatScope.read(context).api.uploadUrl(id);
    final ok = await launchUrl(
      Uri.parse(url),
      mode: LaunchMode.externalApplication,
    );
    if (!ok && context.mounted) {
      showGlassToast(
        context,
        "Couldn't open ${file.name}",
        icon: Icons.error_outline_rounded,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: () => _open(context),
      semanticLabel: 'Open ${file.name}',
      pressedScale: 0.98,
      haptics: false,
      child: Container(
        width: width,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
        decoration: BoxDecoration(
          color: AppColors.bubble,
          borderRadius: BorderRadius.circular(18),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              file.name,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 14.5,
                height: 1.3,
                fontWeight: FontWeight.w600,
                color: AppColors.ink,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              file.detail,
              style: const TextStyle(
                fontSize: 12.5,
                color: AppColors.inkSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Caption extends StatelessWidget {
  const _Caption(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(fontSize: 11.5, color: AppColors.inkTertiary),
    );
  }
}

class _ErrorCaption extends StatelessWidget {
  const _ErrorCaption({required this.message, this.onRetry, this.onDiscard});

  final String message;
  final VoidCallback? onRetry;
  final VoidCallback? onDiscard;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      alignment: WrapAlignment.end,
      spacing: 10,
      children: [
        Text(
          "Not sent · $message",
          style: const TextStyle(fontSize: 12, color: AppColors.danger),
        ),
        if (onRetry != null) _TextAction(label: 'Retry', onTap: onRetry!),
        if (onDiscard != null) _TextAction(label: 'Delete', onTap: onDiscard!),
      ],
    );
  }
}

class _TextAction extends StatelessWidget {
  const _TextAction({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      pressedScale: 0.92,
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 12.5,
          fontWeight: FontWeight.w600,
          color: AppColors.ink,
        ),
      ),
    );
  }
}

class _ImageStrip extends StatelessWidget {
  const _ImageStrip({required this.images, required this.maxWidth});

  final List<ChatImage> images;
  final double maxWidth;

  @override
  Widget build(BuildContext context) {
    final single = images.length == 1;
    final size = single
        ? math.min(220.0, maxWidth)
        : math.min(104.0, (maxWidth - 12) / 3);
    return Wrap(
      alignment: WrapAlignment.end,
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final image in images)
          Pressable(
            pressedScale: 0.97,
            haptics: false,
            semanticLabel: 'Photo',
            onTap: () => showImageViewer(context, image),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(16),
              child: SizedBox(
                width: size,
                height: single ? size * 0.75 : size,
                child: ChatImageView(image: image),
              ),
            ),
          ),
      ],
    );
  }
}

class ChatImageView extends StatelessWidget {
  const ChatImageView({
    super.key,
    required this.image,
    this.fit = BoxFit.cover,
  });

  final ChatImage image;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) {
    final bytes = image.bytes;
    if (bytes != null) {
      return Image.memory(bytes, fit: fit, gaplessPlayback: true);
    }
    final id = image.uploadId;
    if (id == null) return const _ImagePlaceholder();
    final api = ChatScope.read(context).api;
    return Image.network(
      api.uploadUrl(id),
      fit: fit,
      gaplessPlayback: true,
      loadingBuilder: (context, child, progress) =>
          progress == null ? child : const _ImagePlaceholder(),
      errorBuilder: (context, error, stack) =>
          const _ImagePlaceholder(broken: true),
    );
  }
}

class _ImagePlaceholder extends StatelessWidget {
  const _ImagePlaceholder({this.broken = false});

  final bool broken;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: AppColors.surface,
      child: Center(
        child: Icon(
          broken ? Icons.broken_image_outlined : Icons.image_outlined,
          color: AppColors.inkTertiary,
        ),
      ),
    );
  }
}

Future<void> showImageViewer(BuildContext context, ChatImage image) async {
  await singleFlight<void>('image', () => _showImageViewer(context, image));
}

Future<void> _showImageViewer(BuildContext context, ChatImage image) {
  return Navigator.of(context, rootNavigator: true).push(
    PageRouteBuilder<void>(
      opaque: false,
      barrierColor: Colors.black,
      transitionDuration: const Duration(milliseconds: 220),
      pageBuilder: (context, animation, _) => FadeTransition(
        opacity: animation,
        child: _ImageViewer(image: image),
      ),
    ),
  );
}

class _ImageViewer extends StatelessWidget {
  const _ImageViewer({required this.image});

  final ChatImage image;

  @override
  Widget build(BuildContext context) {
    final padding = MediaQuery.paddingOf(context);
    return Material(
      color: Colors.black,
      child: Stack(
        children: [
          Positioned.fill(
            child: InteractiveViewer(
              maxScale: 5,
              child: Center(
                child: ChatImageView(image: image, fit: BoxFit.contain),
              ),
            ),
          ),
          Positioned(
            top: padding.top + 6,
            left: 16,
            child: GlassCircleButton(
              icon: Icons.close_rounded,
              semanticLabel: 'Close',
              settings: GlassPresets.darkControl,
              iconColor: Colors.white,
              onTap: () => popRoute(context),
            ),
          ),
        ],
      ),
    );
  }
}

class TypingBubble extends StatefulWidget {
  const TypingBubble({super.key, this.label});

  final String? label;

  @override
  State<TypingBubble> createState() => _TypingBubbleState();
}

class _TypingBubbleState extends State<TypingBubble>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            margin: const EdgeInsets.only(bottom: 14),
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
            decoration: const BoxDecoration(
              color: AppColors.bubble,
              borderRadius: BorderRadius.only(
                topLeft: Radius.circular(22),
                topRight: Radius.circular(22),
                bottomRight: Radius.circular(22),
                bottomLeft: Radius.circular(6),
              ),
            ),
            child: Semantics(
              label: 'Assistant is typing',
              child: AnimatedBuilder(
                animation: _controller,
                builder: (context, _) {
                  return Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [for (var i = 0; i < 3; i++) _dot(i)],
                  );
                },
              ),
            ),
          ),
          if (widget.label != null)
            Padding(
              padding: const EdgeInsets.only(left: 10, bottom: 14),
              child: Text(
                widget.label!,
                style: const TextStyle(
                  fontSize: 13,
                  color: AppColors.inkTertiary,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _dot(int index) {
    final phase = (_controller.value - index / 3) * 2 * math.pi;
    final wave = (math.sin(phase) + 1) / 2;
    return Padding(
      padding: EdgeInsets.only(left: index == 0 ? 0 : 5),
      child: Transform.translate(
        offset: Offset(0, -3 * wave),
        child: Container(
          width: 7,
          height: 7,
          decoration: BoxDecoration(
            color: AppColors.inkSecondary.withValues(alpha: 0.35 + 0.5 * wave),
            shape: BoxShape.circle,
          ),
        ),
      ),
    );
  }
}
