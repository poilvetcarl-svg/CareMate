package com.mycaremate.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

/**
 * CareMate Android app: the full web product in a WebView, plus the one thing
 * the web cannot do — reading real watch data via Health Connect and syncing
 * it to the CareMate backend so Tomo XP reflects verified activity.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    private val permissionLauncher =
        registerForActivityResult(PermissionController.createRequestPermissionResultContract()) { granted ->
            if (granted.containsAll(HealthConnectSync.PERMISSIONS)) {
                linkAndSync()
            } else {
                Toast.makeText(this, "Health Connect permission is needed to sync your watch.", Toast.LENGTH_LONG).show()
            }
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = FrameLayout(this)
        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
            )
        }
        CookieManager.getInstance().setAcceptCookie(true)

        val syncBtn = Button(this).apply {
            text = getString(R.string.sync_watch)
            setBackgroundColor(0xFFFF6B6B.toInt())
            setTextColor(0xFFFFFFFF.toInt())
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                android.view.Gravity.BOTTOM or android.view.Gravity.END
            ).apply { setMargins(0, 0, 40, 140) }
            setOnClickListener { startWatchSync() }
        }

        root.addView(webView)
        root.addView(syncBtn)
        setContentView(root)

        webView.loadUrl(Api.BASE_URL)

        // If already linked, refresh data quietly on every app open
        if (Api.getToken(this) != null) {
            lifecycleScope.launch { runCatching { HealthConnectSync.syncNow(this@MainActivity) } }
        }
    }

    private fun startWatchSync() {
        val status = HealthConnectClient.getSdkStatus(this)
        if (status != HealthConnectClient.SDK_AVAILABLE) {
            Toast.makeText(this, "Please install/update Health Connect from the Play Store first.", Toast.LENGTH_LONG).show()
            return
        }
        val cookies = CookieManager.getInstance().getCookie(Api.BASE_URL)
        if (cookies == null || !cookies.contains("session=")) {
            Toast.makeText(this, "Sign in to CareMate first, then tap Sync again.", Toast.LENGTH_LONG).show()
            return
        }
        permissionLauncher.launch(HealthConnectSync.PERMISSIONS)
    }

    private fun linkAndSync() {
        lifecycleScope.launch {
            val cookies = CookieManager.getInstance().getCookie(Api.BASE_URL) ?: return@launch
            val token = runCatching { Api.link(this@MainActivity, cookies) }.getOrNull()
            if (token == null) {
                Toast.makeText(this@MainActivity, "Could not link your account, please try again.", Toast.LENGTH_LONG).show()
                return@launch
            }
            val saved = runCatching { HealthConnectSync.syncNow(this@MainActivity) }.getOrDefault(0)
            Toast.makeText(this@MainActivity, "Watch connected. Synced $saved day(s) of data.", Toast.LENGTH_LONG).show()
            schedulePeriodicSync()
            webView.reload()
        }
    }

    private fun schedulePeriodicSync() {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(6, TimeUnit.HOURS).build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "caremate-health-sync", ExistingPeriodicWorkPolicy.UPDATE, request
        )
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }
}
