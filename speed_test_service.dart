// فایل جدید: lib/services/speed_test_service.dart

import 'dart:async';
import 'package:dio/dio.dart';

class SpeedTestService {
  final Dio _dio = Dio();

  // یک URL برای یک فایل تست با حجم مشخص (مثلا 5 مگابایت)
  // می توانید این URL را با یک فایل روی سرور خودتان جایگزین کنید
  static const String _testFileUrl =
      'http://ipv4.download.thinkbroadband.com/5MB.zip';
  static const double _fileSizeInMb = 5.0 * 8; // 5 مگابایت * 8 = 40 مگابیت

  // این تابع اصلی برای تست سرعت است
  Future<double> testDownloadSpeed() async {
    print("DEBUG: [Speed Test] - Starting download test...");

    final stopwatch = Stopwatch()..start();
    try {
      // با استفاده از dio فایل را دانلود می کنیم ولی آن را ذخیره نمی کنیم
      // فقط به بایت های آن نیاز داریم
      await _dio.get<List<int>>(
        _testFileUrl,
        options: Options(
          responseType: ResponseType.bytes, // مهم: برای جلوگیری از ذخیره فایل
        ),
      );
      stopwatch.stop();

      final durationInSeconds = stopwatch.elapsed.inMilliseconds / 1000.0;
      if (durationInSeconds == 0) return 0.0; // جلوگیری از تقسیم بر صفر

      // محاسبه سرعت به مگابیت بر ثانیه (Mbps)
      final speedMbps = _fileSizeInMb / durationInSeconds;

      print(
        "DEBUG: [Speed Test] - Success! Speed: ${speedMbps.toStringAsFixed(2)} Mbps",
      );
      return speedMbps;
    } on DioException catch (e) {
      print("DEBUG: [Speed Test] - FAILED. Reason: ${e.message}");
      return 0.0; // در صورت خطا، سرعت را صفر برمیگردانیم
    }
  }
}
