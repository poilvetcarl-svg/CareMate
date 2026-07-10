package com.mycaremate.app

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import org.json.JSONArray
import org.json.JSONObject
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Reads the last 7 days from Health Connect, aggregates one row per day,
 * and posts it to the CareMate backend. Only ever READS health data, and
 * only the five metrics the product actually uses.
 */
object HealthConnectSync {

    val PERMISSIONS = setOf(
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(RestingHeartRateRecord::class),
        HealthPermission.getReadPermission(HeartRateVariabilityRmssdRecord::class),
        HealthPermission.getReadPermission(OxygenSaturationRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
    )

    private class DayAgg {
        var steps = 0L
        var sleepMin = 0L
        var restingHr = mutableListOf<Long>()
        var hrv = mutableListOf<Double>()
        var spo2 = mutableListOf<Double>()
        var activeMin = 0L
    }

    /** Returns the number of days synced to the server. */
    suspend fun syncNow(context: Context): Int {
        val token = Api.getToken(context) ?: return 0
        val client = HealthConnectClient.getOrCreate(context)
        val zone = ZoneId.systemDefault()
        val today = LocalDate.now(zone)
        val start = today.minusDays(6).atStartOfDay(zone).toInstant()
        val end = Instant.now()
        val filter = TimeRangeFilter.between(start, end)
        val days = HashMap<LocalDate, DayAgg>()
        fun agg(t: Instant) = days.getOrPut(t.atZone(zone).toLocalDate()) { DayAgg() }

        client.readRecords(ReadRecordsRequest(StepsRecord::class, filter)).records
            .forEach { agg(it.startTime).steps += it.count }
        client.readRecords(ReadRecordsRequest(SleepSessionRecord::class, filter)).records
            .forEach {
                // Credit sleep to the wake-up day
                agg(it.endTime).sleepMin += Duration.between(it.startTime, it.endTime).toMinutes()
            }
        client.readRecords(ReadRecordsRequest(RestingHeartRateRecord::class, filter)).records
            .forEach { agg(it.time).restingHr.add(it.beatsPerMinute) }
        client.readRecords(ReadRecordsRequest(HeartRateVariabilityRmssdRecord::class, filter)).records
            .forEach { agg(it.time).hrv.add(it.heartRateVariabilityMillis) }
        client.readRecords(ReadRecordsRequest(OxygenSaturationRecord::class, filter)).records
            .forEach { agg(it.time).spo2.add(it.percentage.value) }
        client.readRecords(ReadRecordsRequest(ExerciseSessionRecord::class, filter)).records
            .forEach { agg(it.startTime).activeMin += Duration.between(it.startTime, it.endTime).toMinutes() }

        val payload = JSONArray()
        for ((day, a) in days) {
            val o = JSONObject().put("day", day.toString())
            if (a.steps > 0) o.put("steps", a.steps)
            if (a.sleepMin > 0) o.put("sleep_min", a.sleepMin)
            if (a.restingHr.isNotEmpty()) o.put("resting_hr", a.restingHr.average().toLong())
            if (a.hrv.isNotEmpty()) o.put("hrv", a.hrv.average().toLong())
            if (a.spo2.isNotEmpty()) o.put("spo2", a.spo2.average().toLong())
            if (a.activeMin > 0) o.put("active_min", a.activeMin)
            payload.put(o)
        }
        if (payload.length() == 0) return 0
        return Api.sync(token, payload)
    }
}
