package com.mounith.remotesystemmonitor

import android.annotation.SuppressLint
import android.content.Context
import android.os.Bundle
import android.view.KeyEvent
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var serverUrlInput: EditText
    private lateinit var openButton: Button
    private lateinit var webView: WebView

    private val prefs by lazy {
        getSharedPreferences("rsm_mobile_prefs", Context.MODE_PRIVATE)
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        serverUrlInput = findViewById(R.id.serverUrlInput)
        openButton = findViewById(R.id.openButton)
        webView = findViewById(R.id.webView)

        val savedUrl = prefs.getString(PREF_URL, DEFAULT_URL) ?: DEFAULT_URL
        serverUrlInput.setText(savedUrl)

        webView.webViewClient = WebViewClient()
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.cacheMode = WebSettings.LOAD_DEFAULT
        webView.settings.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE

        openButton.setOnClickListener {
            loadDashboardUrl()
        }

        loadDashboardUrl()
    }

    private fun loadDashboardUrl() {
        var url = serverUrlInput.text.toString().trim()
        if (url.isEmpty()) return

        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://$url"
        }

        prefs.edit().putString(PREF_URL, url).apply()
        webView.loadUrl(url)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {
            webView.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    companion object {
        private const val PREF_URL = "server_url"
        private const val DEFAULT_URL = "http://192.168.29.180:8080"
    }
}
