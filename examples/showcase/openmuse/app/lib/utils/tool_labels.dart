import 'package:flutter/material.dart';

class ToolLabel {
  const ToolLabel(this.icon, this.done, this.running);

  final IconData icon;
  final String done;
  final String running;

  String text({required bool inProgress}) => inProgress ? running : done;

  static String _host(String url) {
    final uri = Uri.tryParse(url);
    if (uri == null || uri.host.isEmpty) return url;
    return uri.host.startsWith('www.') ? uri.host.substring(4) : uri.host;
  }

  static String _quote(String value) => value.isEmpty ? '' : ' “$value”';

  static ToolLabel of(String? tool, String preview) {
    final name = tool ?? '';
    if (name == 'browser_navigate') {
      final target = switch (preview) {
        'back' => 'the previous page',
        'forward' => 'the next page',
        'reload' => 'the page again',
        _ => _host(preview),
      };
      return ToolLabel(
        Icons.public_rounded,
        'Opened $target',
        'Opening $target',
      );
    }
    if (name.startsWith('browser_')) {
      final action = name.substring(8);
      return switch (action) {
        'screenshot' || 'zoom' => const ToolLabel(
          Icons.public_rounded,
          'Looked at the page',
          'Looking at the page',
        ),
        'read_page' || 'get_page_text' || 'find' => const ToolLabel(
          Icons.article_outlined,
          'Read the page',
          'Reading the page',
        ),
        'type' => ToolLabel(
          Icons.keyboard_outlined,
          'Typed${_quote(preview)}',
          'Typing',
        ),
        'key' || 'hold_key' => ToolLabel(
          Icons.keyboard_outlined,
          'Pressed $preview',
          'Pressing $preview',
        ),
        'scroll' || 'scroll_to' => const ToolLabel(
          Icons.swap_vert_rounded,
          'Scrolled the page',
          'Scrolling',
        ),
        'form_input' => const ToolLabel(
          Icons.edit_note_rounded,
          'Filled in a form',
          'Filling in a form',
        ),
        'file_upload' => const ToolLabel(
          Icons.upload_file_outlined,
          'Uploaded a file',
          'Uploading a file',
        ),
        'takeover' => const ToolLabel(
          Icons.back_hand_outlined,
          'Asked you to take over',
          'Waiting for you',
        ),
        'wait' => const ToolLabel(
          Icons.hourglass_empty_rounded,
          'Waited for the page',
          'Waiting for the page',
        ),
        'new_tab' ||
        'switch_tab' ||
        'close_tab' ||
        'list_tabs' => const ToolLabel(
          Icons.tab_outlined,
          'Switched tabs',
          'Switching tabs',
        ),
        'read_console' ||
        'read_network' ||
        'javascript_exec' => const ToolLabel(
          Icons.code_rounded,
          'Inspected the page',
          'Inspecting the page',
        ),
        _ => const ToolLabel(
          Icons.ads_click_rounded,
          'Clicked on the page',
          'Clicking',
        ),
      };
    }
    if (name.startsWith('computer_')) {
      final action = name.substring(9);
      return switch (action) {
        'screenshot' || 'zoom' => const ToolLabel(
          Icons.desktop_windows_outlined,
          'Looked at the screen',
          'Looking at the screen',
        ),
        'type' => ToolLabel(
          Icons.keyboard_outlined,
          'Typed${_quote(preview)}',
          'Typing',
        ),
        'key' || 'hold_key' => ToolLabel(
          Icons.keyboard_outlined,
          'Pressed $preview',
          'Pressing $preview',
        ),
        'scroll' => const ToolLabel(
          Icons.swap_vert_rounded,
          'Scrolled',
          'Scrolling',
        ),
        'open_app' => ToolLabel(
          Icons.apps_rounded,
          'Opened $preview',
          'Opening $preview',
        ),
        'list_apps' => const ToolLabel(
          Icons.apps_rounded,
          'Checked the open apps',
          'Checking the open apps',
        ),
        'request_access' => const ToolLabel(
          Icons.lock_open_rounded,
          'Asked to use an app',
          'Asking to use an app',
        ),
        'takeover' => const ToolLabel(
          Icons.back_hand_outlined,
          'Asked you to take over',
          'Waiting for you',
        ),
        'wait' => const ToolLabel(
          Icons.hourglass_empty_rounded,
          'Waited',
          'Waiting',
        ),
        'cursor_position' || 'mouse_move' => const ToolLabel(
          Icons.mouse_outlined,
          'Moved the pointer',
          'Moving the pointer',
        ),
        'actions' => const ToolLabel(
          Icons.desktop_windows_outlined,
          'Used the computer',
          'Using the computer',
        ),
        _ => const ToolLabel(Icons.ads_click_rounded, 'Clicked', 'Clicking'),
      };
    }
    return switch (name) {
      'shell' => const ToolLabel(
        Icons.terminal_rounded,
        'Ran a command',
        'Running a command',
      ),
      'shell_input' => const ToolLabel(
        Icons.terminal_rounded,
        'Checked a command',
        'Checking a command',
      ),
      'view_image' => const ToolLabel(
        Icons.image_outlined,
        'Looked at an image',
        'Looking at an image',
      ),
      'share_file' => ToolLabel(
        Icons.ios_share_rounded,
        'Shared ${preview.split('/').last}',
        'Sharing a file',
      ),
      'ask_user' => ToolLabel(
        Icons.help_outline_rounded,
        'Asked${_quote(preview)}',
        'Waiting for your answer',
      ),
      'schedule_task' => ToolLabel(
        Icons.schedule_rounded,
        'Set up a routine${_quote(preview)}',
        'Setting up a routine',
      ),
      'list_scheduled_tasks' => const ToolLabel(
        Icons.schedule_rounded,
        'Checked your routines',
        'Checking routines',
      ),
      'cancel_scheduled_task' => const ToolLabel(
        Icons.schedule_rounded,
        'Cancelled a routine',
        'Cancelling a routine',
      ),
      'load_skill' => ToolLabel(
        Icons.auto_awesome_outlined,
        'Used the $preview skill',
        'Loading a skill',
      ),
      'tool_search' => const ToolLabel(
        Icons.manage_search_rounded,
        'Looked for tools',
        'Looking for tools',
      ),
      _ => ToolLabel(Icons.build_outlined, _humanize(name), _humanize(name)),
    };
  }

  static String activity(String? tool) {
    final name = tool ?? '';
    if (name.startsWith('browser_')) return 'Using the browser';
    if (name.startsWith('computer_')) return 'Using your computer';
    return switch (name) {
      'shell' || 'shell_input' => 'Running a command',
      'ask_user' => 'Waiting for your answer',
      'schedule_task' => 'Setting up a routine',
      'share_file' => 'Sharing a file',
      'view_image' => 'Looking at an image',
      'load_skill' => 'Loading a skill',
      '' => 'Thinking',
      _ => _humanize(name),
    };
  }

  static String _humanize(String name) {
    if (name.isEmpty) return 'Working';
    final words = name.replaceAll('_', ' ').trim();
    return words[0].toUpperCase() + words.substring(1);
  }
}
