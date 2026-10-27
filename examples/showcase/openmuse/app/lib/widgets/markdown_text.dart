import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../glass/glass_toast.dart';
import '../theme/app_theme.dart';

class MarkdownText extends StatefulWidget {
  const MarkdownText(
    this.text, {
    super.key,
    this.color = AppColors.ink,
    this.fontSize = 15.5,
  });

  final String text;
  final Color color;
  final double fontSize;

  @override
  State<MarkdownText> createState() => _MarkdownTextState();
}

sealed class _Block {}

class _Paragraph extends _Block {
  _Paragraph(this.text);
  final String text;
}

class _Heading extends _Block {
  _Heading(this.text, this.level);
  final String text;
  final int level;
}

class _ListItem extends _Block {
  _ListItem(this.text, this.marker, this.indent);
  final String text;
  final String marker;
  final int indent;
}

class _Code extends _Block {
  _Code(this.text);
  final String text;
}

class _Rule extends _Block {}

class _MarkdownTextState extends State<MarkdownText> {
  final List<TapGestureRecognizer> _recognizers = [];

  static final RegExp _bullet = RegExp(r'^(\s*)([-*•])\s+(.*)$');
  static final RegExp _numbered = RegExp(r'^(\s*)(\d{1,3}[.)])\s+(.*)$');
  static final RegExp _heading = RegExp(r'^(#{1,4})\s+(.*)$');
  static final RegExp _inline = RegExp(
    r'(\*\*(.+?)\*\*)|(`([^`]+)`)|(\[([^\]]+)\]\((https?://[^)\s]+)\))|(https?://[^\s<>()]+[^\s<>().,;:!?，。])',
  );

  @override
  void dispose() {
    _clearRecognizers();
    super.dispose();
  }

  void _clearRecognizers() {
    for (final recognizer in _recognizers) {
      recognizer.dispose();
    }
    _recognizers.clear();
  }

  List<_Block> _parse(String source) {
    final blocks = <_Block>[];
    final paragraph = <String>[];
    void flush() {
      if (paragraph.isNotEmpty) {
        blocks.add(_Paragraph(paragraph.join('\n')));
        paragraph.clear();
      }
    }

    final lines = source.replaceAll('\r\n', '\n').split('\n');
    for (var i = 0; i < lines.length; i++) {
      final line = lines[i];
      if (line.trimLeft().startsWith('```')) {
        flush();
        final code = <String>[];
        i++;
        while (i < lines.length && !lines[i].trimLeft().startsWith('```')) {
          code.add(lines[i]);
          i++;
        }
        blocks.add(_Code(code.join('\n')));
        continue;
      }
      if (line.trim().isEmpty) {
        flush();
        continue;
      }
      if (RegExp(r'^\s*(---|\*\*\*|___)\s*$').hasMatch(line)) {
        flush();
        blocks.add(_Rule());
        continue;
      }
      final heading = _heading.firstMatch(line);
      if (heading != null) {
        flush();
        blocks.add(_Heading(heading.group(2)!, heading.group(1)!.length));
        continue;
      }
      final bullet = _bullet.firstMatch(line);
      if (bullet != null) {
        flush();
        blocks.add(
          _ListItem(bullet.group(3)!, '•', bullet.group(1)!.length ~/ 2),
        );
        continue;
      }
      final numbered = _numbered.firstMatch(line);
      if (numbered != null) {
        flush();
        blocks.add(
          _ListItem(
            numbered.group(3)!,
            numbered.group(2)!,
            numbered.group(1)!.length ~/ 2,
          ),
        );
        continue;
      }
      paragraph.add(line);
    }
    flush();
    return blocks;
  }

  Future<void> _open(String url) async {
    final uri = Uri.tryParse(url);
    if (uri == null) return;
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok && mounted) {
      await Clipboard.setData(ClipboardData(text: url));
      if (mounted) {
        showGlassToast(context, 'Link copied', icon: Icons.link_rounded);
      }
    }
  }

  List<InlineSpan> _spans(String text, TextStyle style) {
    final spans = <InlineSpan>[];
    var start = 0;
    for (final match in _inline.allMatches(text)) {
      if (match.start > start) {
        spans.add(TextSpan(text: text.substring(start, match.start)));
      }
      if (match.group(1) != null) {
        spans.add(
          TextSpan(
            text: match.group(2),
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        );
      } else if (match.group(3) != null) {
        spans.add(
          TextSpan(
            text: match.group(4),
            style: TextStyle(
              fontFamily: 'monospace',
              fontSize: style.fontSize! * 0.9,
              backgroundColor: const Color(0x12000000),
            ),
          ),
        );
      } else {
        final label = match.group(6) ?? match.group(8)!;
        final url = match.group(7) ?? match.group(8)!;
        final recognizer = TapGestureRecognizer()..onTap = () => _open(url);
        _recognizers.add(recognizer);
        spans.add(
          TextSpan(
            text: label,
            recognizer: recognizer,
            style: const TextStyle(
              color: AppColors.accent,
              decoration: TextDecoration.underline,
              decorationColor: Color(0x665B5BF0),
            ),
          ),
        );
      }
      start = match.end;
    }
    if (start < text.length) spans.add(TextSpan(text: text.substring(start)));
    return spans;
  }

  @override
  Widget build(BuildContext context) {
    _clearRecognizers();
    final base = TextStyle(
      fontSize: widget.fontSize,
      height: 1.42,
      color: widget.color,
    );
    final blocks = _parse(widget.text);
    final children = <Widget>[];
    for (var i = 0; i < blocks.length; i++) {
      final block = blocks[i];
      final gap = i == 0
          ? 0.0
          : (block is _ListItem && blocks[i - 1] is _ListItem ? 3.0 : 9.0);
      final Widget child = switch (block) {
        _Paragraph(:final text) => Text.rich(
          TextSpan(children: _spans(text, base)),
          style: base,
        ),
        _Heading(:final text, :final level) => Text.rich(
          TextSpan(children: _spans(text, base)),
          style: base.copyWith(
            fontSize:
                widget.fontSize +
                (level <= 1
                    ? 4
                    : level == 2
                    ? 2.5
                    : 1),
            fontWeight: FontWeight.w700,
            height: 1.3,
          ),
        ),
        _ListItem(:final text, :final marker, :final indent) => Padding(
          padding: EdgeInsets.only(left: 14.0 * indent),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: marker == '•' ? 16 : 24,
                child: Text(
                  marker,
                  style: base.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              Expanded(
                child: Text.rich(
                  TextSpan(children: _spans(text, base)),
                  style: base,
                ),
              ),
            ],
          ),
        ),
        _Code(:final text) => Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: widget.color == Colors.white
                ? const Color(0x22FFFFFF)
                : const Color(0x0D000000),
            borderRadius: BorderRadius.circular(12),
          ),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Text(
              text,
              style: base.copyWith(
                fontFamily: 'monospace',
                fontSize: widget.fontSize - 2.5,
                height: 1.4,
              ),
            ),
          ),
        ),
        _Rule() => const Divider(
          height: 8,
          thickness: 0.5,
          color: AppColors.hairline,
        ),
      };
      children.add(
        Padding(
          padding: EdgeInsets.only(top: gap),
          child: child,
        ),
      );
    }
    return SelectionArea(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: children,
      ),
    );
  }
}
