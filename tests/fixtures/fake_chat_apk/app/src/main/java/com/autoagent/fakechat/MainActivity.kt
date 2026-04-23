package com.autoagent.fakechat

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val input = findViewById<EditText>(R.id.input)
        val send = findViewById<Button>(R.id.send)
        val list = findViewById<LinearLayout>(R.id.responses)
        val reset = findViewById<Button>(R.id.newChat)

        send.setOnClickListener {
            val prompt = input.text.toString()
            if (prompt.isBlank()) {
                return@setOnClickListener
            }

            val view = TextView(this).apply {
                text = "echo: $prompt"
                textSize = 18f
            }
            list.addView(view)
            input.setText("")
        }

        reset.setOnClickListener {
            list.removeAllViews()
        }
    }
}
