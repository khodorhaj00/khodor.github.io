package com.styro3d.rhino_viewer

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.widget.Toast
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.util.UUID
import java.util.concurrent.Executors

/**
 * Receives `.3dm` files from ACTION_VIEW / ACTION_SEND intents, copies them to
 * `cacheDir/incoming/<id>/<displayName>` after checking the Rhino magic bytes, and
 * hands the path to Dart over the intent MethodChannel (ARCHITECTURE.md §3.3).
 * Dart deletes the per-intent directory once the file is imported.
 */
class MainActivity : FlutterActivity() {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val copyExecutor = Executors.newSingleThreadExecutor()
    private var channel: MethodChannel? = null

    /** A file that arrived before Dart asked for it via getInitialFile(). */
    private var pendingPath: String? = null

    /** Set once Dart has called getInitialFile(); later files are pushed with onFile(). */
    private var dartListening = false

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).apply {
            setMethodCallHandler { call, result ->
                if (call.method == "getInitialFile") {
                    dartListening = true
                    result.success(pendingPath)
                    pendingPath = null
                } else {
                    result.notImplemented()
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // A recreated activity (rotation, process restore) must not re-import the launch file.
        if (savedInstanceState == null) handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    override fun onDestroy() {
        copyExecutor.shutdown()
        super.onDestroy()
    }

    private fun handleIntent(intent: Intent?) {
        val uri = incomingUri(intent)
        if (uri == null) {
            // The */* SEND filter lists the app in every share sheet; a text or link
            // share carries no stream and would otherwise just open Home silently.
            if (intent?.action == Intent.ACTION_SEND) toast("Share a .3dm file to open it")
            return
        }
        copyExecutor.execute {
            val outcome = try {
                copyIncoming(uri)
            } catch (e: IOException) {
                Outcome.Failed(e.message ?: "read error")
            } catch (e: SecurityException) {
                Outcome.Failed("permission denied")
            } catch (e: RuntimeException) {
                // Malformed provider URIs surface as IllegalArgument/State exceptions.
                Outcome.Failed(e.message ?: e.javaClass.simpleName)
            }
            mainHandler.post { if (!isFinishing && !isDestroyed) onCopied(outcome) }
        }
    }

    private fun incomingUri(intent: Intent?): Uri? = when (intent?.action) {
        Intent.ACTION_VIEW -> intent.data
        Intent.ACTION_SEND -> streamExtra(intent)
        else -> null
    }

    private fun streamExtra(intent: Intent): Uri? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(Intent.EXTRA_STREAM)
        }

    private fun copyIncoming(uri: Uri): Outcome {
        val input = contentResolver.openInputStream(uri) ?: return Outcome.Failed("cannot open")
        return input.use<InputStream, Outcome> { stream ->
            val header = ByteArray(MAGIC.size)
            if (!readFully(stream, header) || !header.contentEquals(MAGIC)) return@use Outcome.NotRhino
            // One directory per intent: a second share of a same-named file must not
            // overwrite a copy Dart may still be importing.
            val dir = File(File(cacheDir, INCOMING_DIR), UUID.randomUUID().toString())
            if (!dir.mkdirs()) return@use Outcome.Failed("cannot create cache dir")
            val target = File(dir, displayName(uri))
            val partial = File(dir, PARTIAL_NAME)
            try {
                partial.outputStream().use { out ->
                    out.write(header)
                    stream.copyTo(out)
                }
                if (!partial.renameTo(target)) throw IOException("cannot rename to ${target.name}")
            } catch (e: Exception) {
                // Never leave a truncated copy behind for Dart to find.
                dir.deleteRecursively()
                throw e
            }
            Outcome.Copied(target.absolutePath)
        }
    }

    private fun readFully(stream: InputStream, buffer: ByteArray): Boolean {
        var offset = 0
        while (offset < buffer.size) {
            val read = stream.read(buffer, offset, buffer.size - offset)
            if (read < 0) return false
            offset += read
        }
        return true
    }

    private fun displayName(uri: Uri): String {
        val fromProvider = if (uri.scheme == "content") queryDisplayName(uri) else null
        val raw = (fromProvider ?: uri.lastPathSegment ?: "")
            .substringAfterLast('/')
            .substringAfterLast('\\')
            .trim()
        return if (raw.isEmpty()) DEFAULT_NAME else raw
    }

    private fun queryDisplayName(uri: Uri): String? = try {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (column >= 0 && cursor.moveToFirst()) cursor.getString(column) else null
        }
    } catch (e: RuntimeException) {
        // Some providers reject the projection or query() altogether although the
        // bytes were readable; the URI's last segment (or DEFAULT_NAME) is used then.
        null
    }

    private fun onCopied(outcome: Outcome) {
        when (outcome) {
            is Outcome.Copied -> deliver(outcome.path)
            Outcome.NotRhino -> toast("Not a Rhino .3dm file")
            is Outcome.Failed -> toast("Could not read the file: ${outcome.reason}")
        }
    }

    private fun deliver(path: String) {
        val ch = channel
        if (dartListening && ch != null) {
            ch.invokeMethod("onFile", path)
        } else {
            pendingPath = path
        }
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private sealed class Outcome {
        data class Copied(val path: String) : Outcome()
        data class Failed(val reason: String) : Outcome()
        data object NotRhino : Outcome()
    }

    private companion object {
        const val CHANNEL = "com.styro3d.rhino_viewer/intent"
        const val INCOMING_DIR = "incoming"
        const val DEFAULT_NAME = "received.3dm"
        const val PARTIAL_NAME = ".partial"
        val MAGIC: ByteArray = "3D Geometry File Format".toByteArray(Charsets.US_ASCII)
    }
}
