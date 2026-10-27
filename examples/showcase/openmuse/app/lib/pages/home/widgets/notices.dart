import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../glass/glass_toast.dart';
import '../../../glass/pressable.dart';
import '../../../models/chat_models.dart';
import '../../../state/chat_store.dart';
import '../../../theme/app_theme.dart';
import 'message_bubble.dart';

const Set<String> visibleNotices = {
  'schedule.fired',
  'openmuse.file',
  'browser.download',
  'skill.loaded',
  'workspace.process',
};

class NoticeView extends StatelessWidget {
  const NoticeView({
    super.key,
    required this.message,
    required this.columnWidth,
  });

  final ChatMessage message;
  final double columnWidth;

  Map<String, dynamic> get _data => message.data is Map
      ? (message.data as Map).cast<String, dynamic>()
      : const {};

  @override
  Widget build(BuildContext context) {
    final data = _data;
    switch (message.kind) {
      case 'schedule.fired':
        return _Chip(
          icon: Icons.schedule_rounded,
          text: 'Routine · ${data['prompt'] ?? ''}',
        );
      case 'skill.loaded':
        return _Chip(
          icon: Icons.auto_awesome_outlined,
          text: 'Using the ${data['name'] ?? ''} skill',
        );
      case 'openmuse.file':
        return _FileCard(data: data, columnWidth: columnWidth);
      case 'browser.download':
        final status = data['status'] as String?;
        final name = (data['name'] as String?) ?? 'a file';
        return _Line(
          icon: status == 'failed'
              ? Icons.error_outline_rounded
              : Icons.download_rounded,
          text: switch (status) {
            'started' => 'Downloading $name…',
            'failed' => 'Download failed: $name',
            _ => 'Downloaded $name to your workspace',
          },
          danger: status == 'failed',
        );
      case 'workspace.process':
        if (message.status != 'in_progress') return const SizedBox.shrink();
        final command = (data['command'] as String?) ?? '';
        return _Line(
          icon: Icons.terminal_rounded,
          text: 'Running in the background: $command',
        );
      default:
        return const SizedBox.shrink();
    }
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: const ShapeDecoration(
            color: AppColors.surface,
            shape: StadiumBorder(),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 14, color: AppColors.inkSecondary),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  text,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: AppColors.inkSecondary,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Line extends StatelessWidget {
  const _Line({required this.icon, required this.text, this.danger = false});

  final IconData icon;
  final String text;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final color = danger ? AppColors.danger : AppColors.inkSecondary;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10, left: 2),
      child: Row(
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 13.5, color: color),
            ),
          ),
        ],
      ),
    );
  }
}

class _FileCard extends StatelessWidget {
  const _FileCard({required this.data, required this.columnWidth});

  final Map<String, dynamic> data;
  final double columnWidth;

  Future<void> _open(BuildContext context, String url) async {
    final ok = await launchUrl(
      Uri.parse(url),
      mode: LaunchMode.externalApplication,
    );
    if (!ok && context.mounted) {
      await Clipboard.setData(ClipboardData(text: url));
      if (context.mounted) {
        showGlassToast(context, 'Link copied', icon: Icons.link_rounded);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final id = data['id'] as String?;
    if (id == null) return const SizedBox.shrink();
    final name = (data['name'] as String?) ?? 'File';
    final mime = (data['mime'] as String?) ?? '';
    final caption = (data['caption'] as String?) ?? '';
    final size = (data['size'] as num?)?.toInt() ?? 0;
    final api = ChatScope.read(context).api;
    final image = ChatImage(uploadId: id);
    final width = columnWidth * 0.72;

    final Widget body;
    if (mime.startsWith('image/')) {
      body = Pressable(
        onTap: () => showImageViewer(context, image),
        semanticLabel: name,
        pressedScale: 0.98,
        haptics: false,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(18),
          child: SizedBox(
            width: width,
            height: width * 0.66,
            child: ChatImageView(image: image),
          ),
        ),
      );
    } else {
      body = Pressable(
        onTap: () => _open(context, api.uploadUrl(id)),
        semanticLabel: 'Open $name',
        pressedScale: 0.98,
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
                name,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 15,
                  height: 1.3,
                  fontWeight: FontWeight.w600,
                  color: AppColors.ink,
                ),
              ),
              const SizedBox(height: 3),
              Text(
                ChatFile(uploadId: id, name: name, size: size).detail,
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

    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            body,
            if (caption.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6, left: 4),
                child: Text(
                  caption,
                  style: const TextStyle(
                    fontSize: 13.5,
                    color: AppColors.inkSecondary,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
