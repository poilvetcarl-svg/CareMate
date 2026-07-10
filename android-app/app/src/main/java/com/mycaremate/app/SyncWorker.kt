package com.mycaremate.app

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

/** Background job: refresh watch data every ~6 hours while the app is installed. */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = try {
        HealthConnectSync.syncNow(applicationContext)
        Result.success()
    } catch (e: Exception) {
        Result.retry()
    }
}
