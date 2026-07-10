package com.mycaremate.app

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Minimal HTTP client for the two CareMate endpoints the app needs. */
object Api {

    const val BASE_URL = "https://mycaremate.me"
    private const val PREFS = "caremate"
    private const val KEY_TOKEN = "sync_token"

    fun getToken(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_TOKEN, null)

    /** Exchange the logged-in WebView session for a long-lived sync token. */
    suspend fun link(context: Context, cookies: String): String = withContext(Dispatchers.IO) {
        val conn = URL("$BASE_URL/api/wearable/link").openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.setRequestProperty("Cookie", cookies)
        conn.setRequestProperty("Content-Type", "application/json")
        conn.doOutput = true
        conn.outputStream.use { it.write("{}".toByteArray()) }
        val body = conn.inputStream.bufferedReader().readText()
        conn.disconnect()
        val token = JSONObject(body).getString("token")
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_TOKEN, token).apply()
        token
    }

    /** Post daily aggregates. Returns the number of days the server saved. */
    suspend fun sync(token: String, days: JSONArray): Int = withContext(Dispatchers.IO) {
        val conn = URL("$BASE_URL/api/wearable/sync").openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.setRequestProperty("Authorization", "Bearer $token")
        conn.setRequestProperty("Content-Type", "application/json")
        conn.doOutput = true
        conn.outputStream.use { it.write(JSONObject().put("days", days).toString().toByteArray()) }
        val body = conn.inputStream.bufferedReader().readText()
        conn.disconnect()
        JSONObject(body).optInt("saved", 0)
    }
}
