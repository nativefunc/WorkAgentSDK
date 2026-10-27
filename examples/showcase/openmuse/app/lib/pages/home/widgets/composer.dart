import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../../glass/glass_presets.dart';
import '../../../glass/glass_surface.dart';
import '../../../glass/pressable.dart';
import '../../../models/chat_models.dart';
import '../../../theme/app_theme.dart';

class PendingAttachment {
  PendingAttachment({required this.bytes, required this.name})
    : isImage = _looksLikeImage(bytes);

  final Uint8List bytes;
  final String name;

  final bool isImage;

  int get size => bytes.length;

  double progress = 0;
  String? uploadId;
  String? error;

  bool get uploaded => uploadId != null;
  bool get uploading => uploadId == null && error == null;

  static bool _looksLikeImage(Uint8List b) {
    bool starts(List<int> sig, [int offset = 0]) {
      if (b.length < offset + sig.length) return false;
      for (var i = 0; i < sig.length; i++) {
        if (b[offset + i] != sig[i]) return false;
      }
      return true;
    }

    return starts(const [0x89, 0x50, 0x4E, 0x47]) ||
        starts(const [0xFF, 0xD8, 0xFF]) ||
        starts(const [0x47, 0x49, 0x46, 0x38]) ||
        (starts(const [0x52, 0x49, 0x46, 0x46]) &&
            starts(const [0x57, 0x45, 0x42, 0x50], 8));
  }
}

const double _buttonSize = 40;

class Composer extends StatelessWidget {
  static const double extrasHeight = 64;

  static const double extrasSpace = extrasHeight + 10;

  const Composer({
    super.key,
    required this.controller,
    required this.focusNode,
    required this.onSend,
    required this.onAttach,
    this.onStop,
    this.running = false,
    this.attachments = const [],
    this.onRemoveAttachment,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final VoidCallback onSend;
  final VoidCallback onAttach;

  final VoidCallback? onStop;
  final bool running;

  final List<PendingAttachment> attachments;
  final ValueChanged<PendingAttachment>? onRemoveAttachment;

  @override
  Widget build(BuildContext context) {
    final hasExtras = attachments.isNotEmpty;
    return GlassSurface(
      radius: 26,
      settings: GlassPresets.panel(),
      padding: const EdgeInsets.all(6),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (hasExtras)
            Padding(
              padding: const EdgeInsets.fromLTRB(6, 6, 6, 4),
              child: SizedBox(
                height: Composer.extrasHeight,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  children: [
                    for (final attachment in attachments)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: _Thumbnail(
                          attachment: attachment,
                          onRemove: onRemoveAttachment == null
                              ? null
                              : () => onRemoveAttachment!(attachment),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              _RoundButton(
                semanticLabel: 'Attach files',
                onTap: onAttach,
                background: Colors.transparent,
                child: const Icon(
                  Icons.add_rounded,
                  size: 26,
                  color: AppColors.ink,
                ),
              ),
              const SizedBox(width: 2),
              Expanded(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: _buttonSize),
                  child: TextField(
                    controller: controller,
                    focusNode: focusNode,
                    minLines: 1,
                    maxLines: 5,
                    textAlignVertical: TextAlignVertical.center,
                    textCapitalization: TextCapitalization.sentences,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => onSend(),
                    style: const TextStyle(
                      fontSize: 16,
                      height: 1.25,
                      leadingDistribution: TextLeadingDistribution.even,
                      color: AppColors.ink,
                    ),
                    decoration: const InputDecoration(
                      hintText: 'Message…',
                      hintStyle: TextStyle(color: AppColors.inkTertiary),
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      isDense: true,
                      contentPadding: EdgeInsets.fromLTRB(4, 11, 4, 9),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 6),
              ValueListenableBuilder<TextEditingValue>(
                valueListenable: controller,
                builder: (context, value, _) {
                  final uploading = attachments.any((a) => a.uploading);
                  final hasContent =
                      value.text.trim().isNotEmpty ||
                      attachments.any((a) => a.uploaded);
                  if (running && !hasContent && onStop != null) {
                    return _RoundButton(
                      semanticLabel: 'Stop',
                      onTap: onStop,
                      background: AppColors.ink,
                      child: const Icon(
                        Icons.stop_rounded,
                        size: 22,
                        color: Colors.white,
                      ),
                    );
                  }
                  final canSend = hasContent && !uploading;
                  return _RoundButton(
                    semanticLabel: 'Send',
                    onTap: canSend ? onSend : null,
                    background: canSend
                        ? AppColors.ink
                        : const Color(0x14000000),
                    child: uploading
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: AppColors.inkTertiary,
                            ),
                          )
                        : Icon(
                            Icons.arrow_upward_rounded,
                            size: 22,
                            color: canSend
                                ? Colors.white
                                : AppColors.inkTertiary,
                          ),
                  );
                },
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Thumbnail extends StatelessWidget {
  const _Thumbnail({required this.attachment, this.onRemove});

  final PendingAttachment attachment;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: attachment.isImage ? 64 : 168,
      height: 64,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned.fill(
            child: attachment.isImage
                ? ClipRRect(
                    borderRadius: BorderRadius.circular(14),
                    child: Image.memory(
                      attachment.bytes,
                      fit: BoxFit.cover,
                      gaplessPlayback: true,
                    ),
                  )
                : _FileTile(name: attachment.name, size: attachment.size),
          ),
          if (attachment.uploading || attachment.error != null)
            Positioned.fill(
              child: Container(
                decoration: BoxDecoration(
                  color: const Color(0x66000000),
                  borderRadius: BorderRadius.circular(14),
                ),
                alignment: Alignment.center,
                child: attachment.error != null
                    ? const Icon(
                        Icons.error_outline_rounded,
                        color: Colors.white,
                        size: 22,
                      )
                    : SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(
                          value: attachment.progress > 0
                              ? attachment.progress
                              : null,
                          strokeWidth: 2.2,
                          color: Colors.white,
                        ),
                      ),
              ),
            ),
          if (onRemove != null)
            Positioned(
              top: 4,
              right: 4,
              child: Pressable(
                onTap: onRemove,
                semanticLabel: 'Remove attachment',
                pressedScale: 0.85,
                child: Container(
                  width: 22,
                  height: 22,
                  decoration: BoxDecoration(
                    color: AppColors.ink,
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white, width: 1.5),
                  ),
                  child: const Icon(
                    Icons.close_rounded,
                    size: 13,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _FileTile extends StatelessWidget {
  const _FileTile({required this.name, required this.size});

  final String name;
  final int size;

  @override
  Widget build(BuildContext context) {
    final file = ChatFile(uploadId: null, name: name, size: size);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 28, 10),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            name,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 13.5,
              fontWeight: FontWeight.w500,
              color: AppColors.ink,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            file.detail,
            maxLines: 1,
            style: const TextStyle(fontSize: 12, color: AppColors.inkTertiary),
          ),
        ],
      ),
    );
  }
}

class _RoundButton extends StatelessWidget {
  const _RoundButton({
    required this.semanticLabel,
    required this.onTap,
    required this.background,
    required this.child,
  });

  final String semanticLabel;
  final VoidCallback? onTap;
  final Color background;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Pressable(
      onTap: onTap,
      semanticLabel: semanticLabel,
      pressedScale: 0.88,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        width: _buttonSize,
        height: _buttonSize,
        decoration: BoxDecoration(color: background, shape: BoxShape.circle),
        alignment: Alignment.center,
        child: child,
      ),
    );
  }
}
