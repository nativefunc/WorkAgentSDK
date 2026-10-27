import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'sse_stub.dart' if (dart.library.js_interop) 'sse_web.dart';

class ApiException implements Exception {
  const ApiException(this.message, {this.status});

  final String message;
  final int? status;

  bool get unauthorized => status == 401;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({required String baseUrl}) : _baseUrl = _normalize(baseUrl) {
    _dio = Dio(
      BaseOptions(
        baseUrl: _baseUrl,
        connectTimeout: const Duration(seconds: 10),
        receiveTimeout: const Duration(seconds: 60),
        sendTimeout: const Duration(seconds: 60),
        contentType: Headers.jsonContentType,
      ),
    );
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final token = this.token;
          if (token != null) options.headers['Authorization'] = 'Bearer $token';
          handler.next(options);
        },
      ),
    );
  }

  late final Dio _dio;
  String _baseUrl;

  String? token;

  void Function()? onUnauthorized;

  String get baseUrl => _baseUrl;
  bool get hasToken => token != null;

  set baseUrl(String value) {
    _baseUrl = _normalize(value);
    _dio.options.baseUrl = _baseUrl;
  }

  static String _normalize(String url) {
    var value = url.trim();
    if (value.isEmpty) return value;
    if (!value.startsWith('http://') && !value.startsWith('https://')) {
      value = 'http://$value';
    }
    while (value.endsWith('/')) {
      value = value.substring(0, value.length - 1);
    }
    return value;
  }

  Future<Map<String, dynamic>> get(String path) =>
      _send(() => _dio.get<dynamic>(path));

  Future<Map<String, dynamic>> post(String path, [Object? body]) =>
      _send(() => _dio.post<dynamic>(path, data: body ?? const {}));

  Future<Map<String, dynamic>> patch(String path, Object body) =>
      _send(() => _dio.patch<dynamic>(path, data: body));

  Future<Map<String, dynamic>> delete(String path) =>
      _send(() => _dio.delete<dynamic>(path));

  Future<Map<String, dynamic>> uploadFile(
    Uint8List bytes,
    String filename, {
    void Function(double progress)? onProgress,
  }) {
    final form = FormData.fromMap({
      'file': MultipartFile.fromBytes(bytes, filename: filename),
    });
    return _send(
      () => _dio.post<dynamic>(
        '/api/uploads',
        data: form,
        onSendProgress: onProgress == null
            ? null
            : (sent, total) {
                if (total > 0) onProgress(sent / total);
              },
      ),
    );
  }

  Future<Map<String, dynamic>> _send(
    Future<Response<dynamic>> Function() request,
  ) async {
    try {
      final response = await request();
      final data = response.data;
      if (data is Map<String, dynamic>) return data;
      return const {};
    } on DioException catch (error) {
      throw _translate(error);
    }
  }

  ApiException _translate(DioException error) {
    final status = error.response?.statusCode;
    if (status == 401) onUnauthorized?.call();
    final data = error.response?.data;
    if (data is Map && data['detail'] != null) {
      final detail = data['detail'];
      if (detail is String) return ApiException(detail, status: status);
      if (detail is List && detail.isNotEmpty && detail.first is Map) {
        final message = (detail.first as Map)['msg'];
        if (message is String) return ApiException(message, status: status);
      }
    }
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.connectionError:
        return const ApiException(
          "Can't reach the server. Check the address and your connection.",
        );
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.sendTimeout:
        return const ApiException('The server took too long to answer.');
      default:
        return ApiException(
          status == null ? 'Something went wrong' : 'Server error ($status)',
          status: status,
        );
    }
  }

  Stream<Map<String, dynamic>> events(
    String path, {
    CancelToken? cancel,
  }) async* {
    final separator = path.contains('?') ? '&' : '?';
    final browser = openEventStream(
      '$_baseUrl$path${separator}token=${Uri.encodeQueryComponent(token ?? '')}',
    );
    if (browser != null) {
      yield* browser;
      return;
    }

    Response<ResponseBody> response;
    try {
      response = await _dio.get<ResponseBody>(
        path,
        cancelToken: cancel,
        options: Options(
          responseType: ResponseType.stream,
          receiveTimeout: const Duration(seconds: 45),
          headers: const {'Accept': 'text/event-stream'},
        ),
      );
    } on DioException catch (error) {
      throw _translate(error);
    }

    final lines = response.data!.stream
        .cast<List<int>>()
        .transform(utf8.decoder)
        .transform(const LineSplitter());
    final buffer = StringBuffer();
    try {
      await for (final line in lines) {
        if (line.isEmpty) {
          if (buffer.isNotEmpty) {
            final text = buffer.toString();
            buffer.clear();
            final decoded = jsonDecode(text);
            if (decoded is Map<String, dynamic>) yield decoded;
          }
          continue;
        }
        if (line.startsWith('data:')) {
          if (buffer.isNotEmpty) buffer.write('\n');
          buffer.write(line.substring(5).trimLeft());
        }
      }
    } on DioException catch (error) {
      if (CancelToken.isCancel(error)) return;
      throw _translate(error);
    }
  }

  String uploadUrl(String uploadId) =>
      '$_baseUrl/api/uploads/$uploadId?token=${Uri.encodeQueryComponent(token ?? '')}';

  Map<String, String> get authHeaders =>
      token == null ? const {} : {'Authorization': 'Bearer $token'};

  Uri controlUri({required String target, String? chatId, String? requestId}) {
    final base = Uri.parse(_baseUrl);
    return base.replace(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      path: '/api/control',
      queryParameters: {
        'target': target,
        if (chatId != null) 'chat_id': chatId,
        if (requestId != null) 'request_id': requestId,
        'token': token ?? '',
      },
    );
  }
}
