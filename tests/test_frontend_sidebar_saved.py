from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_sidebar_uses_history_and_saved_modes_only():
    html = _read("frontend/index.html")
    assert 'data-library-mode="history"' in html
    assert 'data-library-mode="saved"' in html
    assert 'data-library-mode="pinned"' not in html
    assert 'data-library-mode="marked"' not in html


def test_saved_action_labels_and_state_keys_present():
    js = _read("frontend/app.js")
    assert "pin-turn" not in js
    assert "mark-turn" not in js
    assert "saved" in js
    assert "data-library-action=\"toggle-save\"" in js


def test_pending_card_uses_step_based_loop_markup_without_query_duplication():
    js = _read("frontend/app.js")
    assert "PIPELINE_STEPS" in js
    assert "pipeline-steps-card" in js
    assert "data-pipeline-step" in js
    assert "Etapa atual:" in js
    assert "pipeline-query-preview" not in js
    assert "shortText(turn.query, 140)" not in js


def test_doc_refs_are_normalized_to_doc_links_even_in_grouped_citations():
    js = _read("frontend/app.js")
    assert "DOC_REF_GROUP_RE" in js
    assert "appendDocRefsFromText" in js
    assert "createDocRefLink" in js
    assert "[DOC. ${docNum}]" in js
    assert "matchAll(/(?:[,;]|\\be\\b)\\s*(\\d+)/gi)" in js


def test_response_microtyping_hooks_exist():
    js = _read("frontend/app.js")
    css = _read("frontend/styles.css")
    assert "microType" in js
    assert "prefers-reduced-motion" in css


def test_saved_library_list_is_compact_and_does_not_stretch_single_card():
    css = _read("frontend/styles.css")
    assert ".library-list" in css
    assert "grid-auto-rows: max-content;" in css
    assert "align-content: start;" in css


def test_rag_config_supports_detailed_group_help_for_fontes_ae():
    js = _read("frontend/app.js")
    assert "RAG_GROUP_HELP" in js
    assert "Fontes A-E" in js
    assert "Busca e Ranking" in js
    assert "Validacao" in js


def test_settings_panel_has_responsive_breakpoints():
    css = _read("frontend/styles.css")
    assert "width: clamp(460px, 36vw, 620px);" in css
    assert "max-height: min(92vh, 1020px);" in css
    assert "transform: translateX(16px);" in css
    assert "transform: translateY(100%);" in css


def test_answer_font_scale_controls_exist_and_are_persisted():
    js = _read("frontend/app.js")
    css = _read("frontend/styles.css")
    assert "answerFontScale" in js
    assert "data-action=\"font-down\"" in js
    assert "data-action=\"font-up\"" in js
    assert "--answer-font-size" in css
    assert "--answer-font-size-mobile" in css
    assert "setProperty(\"--answer-font-size\"" in js
    assert "setProperty(\"--answer-font-size-mobile\"" in js


def test_submit_query_clears_input_after_send():
    js = _read("frontend/app.js")
    assert "queryInput.value = \"\";" in js


def test_submit_query_surfaces_generation_config_warning_when_present():
    js = _read("frontend/app.js")
    assert "generation_warning" in js
    assert "AVISO DE CONFIGURACAO" in js


def test_assistant_label_icon_alignment_is_adjusted():
    css = _read("frontend/styles.css")
    assert "content: \"\\2696\\FE0E\";" in css
    assert "line-height: 1;" in css


def test_onboarding_modal_and_about_sections_exist_in_layout():
    html = _read("frontend/index.html")
    assert 'id="onboardingModal"' in html
    assert 'id="closeOnboardingBtn"' in html
    assert "Primeiros passos com API Gemini" in html


def test_onboarding_supports_one_time_gemini_key_setup():
    html = _read("frontend/index.html")
    js = _read("frontend/app.js")
    assert 'id="onboardingApiKeyInput"' in html
    assert 'id="onboardingSaveKeyBtn"' in html
    assert 'id="onboardingKeyStatus"' in html
    assert "/api/gemini/config" in js
    assert "onboardingSaveKeyBtn" in js


def test_onboarding_pricing_cards_translate_request_impact():
    html = _read("frontend/index.html")
    assert "Reranker local" in html
    assert "Reranker Gemini" in html
    assert "requisicoes por consulta" in html.lower()
    assert "cota gratuita" in html.lower()
    assert "gemini-2.5-pro" in html
    assert "gemini-embedding-001" not in html
    assert "Estimativa por pergunta no Ratio" in html


def test_about_modal_replaces_about_sections_in_settings():
    html = _read("frontend/index.html")
    assert 'data-open-about' in html
    assert 'id="aboutModal"' in html
    assert 'id="aboutTabs"' in html
    assert "Sobre o acervo" in html
    assert "Sobre o autor e apoio" in html
    assert "<strong>Instagram:</strong>" in html
    assert "<strong>E-mail:</strong>" in html
    assert "apoio-pix.jpeg" in html
    assert 'id="pixKeyText"' in html

    settings_slice = html.split('<aside id="settingsPanel"', 1)[1]
    assert "<summary>Sobre o acervo</summary>" not in settings_slice
    assert "<summary>Sobre o autor e apoio</summary>" not in settings_slice


def test_about_structure_tab_shows_document_counts():
    html = _read("frontend/index.html")
    assert "Sumula vinculante" in html
    assert "63 documentos" in html
    assert "Tema repetitivo STJ" in html
    assert "689 documentos" in html
    assert "Sumula" in html
    assert "1.377 documentos" in html
    assert "Acordao" in html
    assert "223.122 documentos" in html
    assert "Decisao monocratica" in html
    assert "286.800 documentos" in html
    assert "Informativo" in html
    assert "16.300 documentos" in html


def test_about_author_copy_mentions_free_access_for_students_and_professionals():
    html = _read("frontend/index.html")
    assert "gratuito" in html
    assert "estudantes e profissionais" in html
    assert "nao podem assumir assinaturas pagas" in html


def test_onboarding_state_and_controls_exist_in_frontend_logic():
    js = _read("frontend/app.js")
    assert "ONBOARDING_STORAGE_KEY" in js
    assert "onboardingSeen" in js
    assert "setOnboardingOpen" in js
    assert "closeOnboardingBtn" in js


def test_settings_has_explicit_save_action_and_model_controls():
    html = _read("frontend/index.html")
    js = _read("frontend/app.js")
    assert 'id="saveRagConfigBtn"' in html
    assert 'id="generationModelInput"' in html
    assert 'id="generationFallbackModelInput"' in html
    assert 'id="geminiRerankModelInput"' in html
    assert "saveRagConfigBtn" in js
    assert "generationModelInput" in js
    assert "generation_fallback_model" in js
    assert "gemini_rerank_model" in js


def test_rag_config_version_migration_hooks_exist_in_frontend_state():
    js = _read("frontend/app.js")
    assert "ragConfigVersion" in js
    assert "resetForNewVersion" in js
    assert "payload?.version" in js
    assert "Preset de resposta atualizado para o modo mais rico" in js


def test_onboarding_key_error_message_points_user_to_api_key_guide():
    js = _read("frontend/app.js")
    assert "Guia de API key" in js
    assert "https://ai.google.dev/gemini-api/docs/api-key" in js


def test_onboarding_key_validation_has_elapsed_feedback_and_timeout():
    js = _read("frontend/app.js")
    assert "ONBOARDING_KEY_VALIDATE_TIMEOUT_MS" in js
    assert "ONBOARDING_KEY_STATUS_PULSE_MS" in js
    assert "Validando chave Gemini..." in js
    assert "A validacao da chave esta demorando" in js
    assert "Ainda validando a chave Gemini" in js
    assert "timeoutMs: ONBOARDING_KEY_VALIDATE_TIMEOUT_MS" in js
    assert "request_timeout" in js


def test_tts_request_has_explicit_timeout_to_avoid_stuck_loading():
    js = _read("frontend/app.js")
    assert "AUDIO_TTS_TIMEOUT_BASE_MS" in js
    assert "AUDIO_TTS_TIMEOUT_PER_1000_CHARS_MS" in js
    assert "AUDIO_TTS_TIMEOUT_MAX_MS" in js
    assert "estimateTtsTimeoutMs" in js
    assert "timeoutLabel: \"A geracao do audio\"" in js
    assert "timeoutMs," in js


def test_tts_error_handling_exposes_trace_id_for_support():
    js = _read("frontend/app.js")
    assert "trace_id" in js
    assert "traceId" in js


def test_frontend_uses_tts_stream_endpoint_for_progressive_audio():
    js = _read("frontend/app.js")
    assert "/api/tts/stream" in js
    assert "event === \"chunk\"" in js
    assert "event === \"done\"" in js
    assert "application/x-ndjson" in js


def test_frontend_audio_ui_has_replay_action_and_dual_progress_bars():
    js = _read("frontend/app.js")
    css = _read("frontend/styles.css")
    assert "data-action=\"replay-audio\"" in js
    assert "data-audio-buffer-turn" in js
    assert "data-audio-play-turn" in js
    assert ".audio-buffer" in css
    assert ".audio-track.loading .audio-buffer::after" in css


def test_frontend_reuses_cached_stream_audio_without_new_tts_generation():
    js = _read("frontend/app.js")
    assert "replayCachedTurnAudio" in js
    assert "audioStreamByMode" in js
    assert "rememberStreamChunkForTurn" in js
    assert "replaceTurnAudioSession" in js


def test_dossie_cards_remove_source_and_level_lines_and_show_tribunal():
    js = _read("frontend/app.js")
    assert "Origem: ${safeText(d.source_label" not in js
    assert "Nivel ${safeText(d.authority_level)" not in js
    assert "Tribunal prolator:" in js


def test_dossie_cards_support_full_document_open_on_card_click():
    js = _read("frontend/app.js")
    css = _read("frontend/styles.css")
    assert "openSourceDocumentByIndex" in js
    assert "data-open-doc=\"1\"" in js
    assert "data-source-action=\"open-inline\"" in js
    assert "source-card-actionable" in css


def test_onboarding_timeout_falls_back_to_save_key_without_validation():
    js = _read("frontend/app.js")
    assert "fallbackSaveResult" in js
    assert "Chave salva sem validacao online" in js
    assert "validate: false" in js
    assert "Falha ao salvar chave apos timeout de validacao" in js


def test_post_json_supports_abort_controller_timeout_option():
    js = _read("frontend/app.js")
    assert "new AbortController()" in js
    assert "controller?.signal" in js
    assert "clearTimeout(timeoutId)" in js
    assert "timeoutLabel" in js


def test_onboarding_and_about_visual_blocks_exist_in_stylesheet():
    css = _read("frontend/styles.css")
    assert ".onboarding-modal" in css
    assert ".onboarding-steps" in css
    assert ".about-modal" in css
    assert ".about-tabs" in css
    assert ".acervo-scale-visual" in css


def test_about_modal_logic_exists_in_frontend_js():
    js = _read("frontend/app.js")
    assert "dataset.aboutOpen" in js
    assert "setAboutOpen" in js
    assert "openAboutBtns" in js
    assert "copyPixKeyBtn" in js


def test_readme_contains_gemini_onboarding_cost_and_support_sections():
    readme = _read("README.md")
    assert "Gemini API onboarding (antes do primeiro uso)" in readme
    assert "Custos de referencia (snapshot 2026-02-24)" in readme
    assert "Apoio ao projeto" in readme


def test_settings_has_meu_acervo_controls():
    html = _read("frontend/index.html")
    settings_slice = html.split('<aside id="settingsPanel"', 1)[1].split('<aside id="acervoPanel"', 1)[0]
    acervo_slice = html.split('<aside id="acervoPanel"', 1)[1]

    assert "Fontes da pesquisa" in settings_slice
    assert 'id="sourceFiltersList"' in settings_slice
    assert 'id="userCorpusFilesInput"' not in settings_slice

    assert "Meu Acervo" in acervo_slice
    assert 'id="userCorpusSources"' in acervo_slice
    assert 'id="userCorpusFilesInput"' in acervo_slice
    assert 'id="indexUserCorpusBtn"' in acervo_slice
    assert 'id="userCorpusStatus"' in acervo_slice
    assert "Indexar ao acervo" in acervo_slice
    assert 'data-open-acervo' in html


def test_frontend_query_payload_includes_sources_and_user_priority():
    js = _read("frontend/app.js")
    assert "sources:" in js
    assert "prefer_user_sources" in js
    assert "source-checkbox" in js


def test_frontend_has_meu_acervo_delete_restore_actions():
    js = _read("frontend/app.js")
    assert "/api/meu-acervo/source/delete" in js
    assert "/api/meu-acervo/source/restore" in js
    assert "restore-source" in js


def test_frontend_meu_acervo_uses_async_job_status_polling():
    js = _read("frontend/app.js")
    assert "/api/meu-acervo/index/jobs/" in js
    assert "eta_seconds" in js


def test_frontend_query_stream_has_timeout_and_uses_real_pipeline_runtime():
    js = _read("frontend/app.js")
    assert "QUERY_STREAM_TIMEOUT_MS" in js
    assert "A consulta juridica" in js
    assert 'makePipelineRuntime("real")' in js


def test_composer_has_visible_contact_strip():
    html = _read("frontend/index.html")
    composer_slice = html.split('<footer class="composer panel-shell">', 1)[1].split("</footer>", 1)[0]

    assert 'class="composer-contact"' in composer_slice
    assert "Contato" in composer_slice
    assert 'href="mailto:contato@ratiojuris.me"' in composer_slice
