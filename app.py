import sys
import configparser

# Azure Speech
import os
import azure.cognitiveservices.speech as speechsdk
import librosa

#Azure Translation
from azure.ai.translation.text import TextTranslationClient, TranslatorCredential
from azure.ai.translation.text.models import InputTextItem
from azure.core.exceptions import HttpResponseError

from flask import Flask, request, abort, session
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    AudioMessage
)

#Config Parser
config = configparser.ConfigParser()
config.read('config.ini')

# Azure Speech Settings
speech_config = speechsdk.SpeechConfig(subscription=config['AzureSpeech']['SPEECH_KEY'], 
                                       region=config['AzureSpeech']['SPEECH_REGION'])
audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
UPLOAD_FOLDER = 'static'


app = Flask(__name__)

app.secret_key = "this is a secret key"

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

channel_access_token = config['Line']['CHANNEL_ACCESS_TOKEN']
channel_secret = config['Line']['CHANNEL_SECRET']
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

handler = WebhookHandler(channel_secret)

configuration = Configuration(
    access_token=channel_access_token
)

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # parse webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def message_text(event):
    translation_result = azure_translate(event.message.text)
    translation_result_hant = session.get("translated_result_hant")
    transliterate_result_hant = azure_transliterate_hant(translation_result_hant)
    translation_result_ja = session.get("translated_result_ja")
    transliterate_result_ja = azure_transliterate_ja(translation_result_ja)
   
    duration_hant = azure_speech_hant(translation_result_hant)
    duration_ja = azure_speech_ja(translation_result_ja)
    
    question = translation_result_hant
    response = azure_custom_question_answer(question)
    response_translated = azure_translate(response)
    response_translated_hant = session.get("translated_result_response_en")
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text="中文" + "\n" + translation_result_hant + "\n" + transliterate_result_hant),
                    AudioMessage(original_content_url=config["Deploy"]["URL"]+"/static/outputaudio_hant.wav", duration=duration_hant),
                    # TextMessage(text="日文" + "\n" + translation_result_ja + "\n" + transliterate_result_ja),
                    # AudioMessage(original_content_url=config["Deploy"]["URL"]+"/static/outputaudio_ja.wav", duration=duration_ja),
                    TextMessage(text=response_translated_hant)
                    ]
            )
        )

def azure_translate(user_input):

    credential = TranslatorCredential(config['AzureTranslator']["Key"], config['AzureTranslator']["Region"])
    text_translator = TextTranslationClient(endpoint=config['AzureTranslator']["EndPoint"], credential=credential)

    try:
        target_languages = ["en", "zh-Hant", "ja", "ko"]
        input_text_elements = [ InputTextItem(text = user_input) ]

        response = text_translator.translate(content = input_text_elements, to = target_languages)
        print(response)
        translation = response[0] if response else None
        session["detected_lang"] = translation['detectedLanguage']['language']
        session["translated_content"] = translation.translations[1].text

        if translation['detectedLanguage']['language'] == "en":
            session["translated_result_en"] = translation.translations[0].text
            session["translated_result_hant"] = translation.translations[1].text
            session["translated_result_ja"] = translation.translations[2].text
            session["translated_result_ko"] = translation.translations[3].text
            return translation.translations[1].text + "\n" + translation.translations[2].text + "\n" + translation.translations[3].text
        elif translation['detectedLanguage']['language'] == "zh-Hant":
            session["translated_result_response_en"] = translation.translations[0].text
            session["translated_result_ja"] = translation.translations[2].text
            session["translated_result_ko"] = translation.translations[3].text
            return translation.translations[0].text + "\n" + translation.translations[2].text + "\n" + translation.translations[3].text
        elif translation['detectedLanguage']['language'] == "ja":
            session["translated_result_hant"] = translation.translations[1].text
            session["translated_result_en"] = translation.translations[0].text
            session["translated_result_ko"] = translation.translations[3].text
            return translation.translations[0].text + "\n" + translation.translations[1].text + "\n" + translation.translations[3].text
        else:
            session["translated_result_hant"] = translation.translations[1].text
            session["translated_result_ja"] = translation.translations[2].text
            session["translated_result_en"] = translation.translations[0].text
            return translation.translations[0].text + "\n" + translation.translations[1].text + "\n" + translation.translations[2].text

    except HttpResponseError as exception:
        print(f"Error Code: {exception.error}")
        print(f"Message: {exception.error.message}")

def azure_transliterate_hant(user_input):
    credential = TranslatorCredential(config['AzureTranslator']["Key"], config['AzureTranslator']["Region"])
    text_translator = TextTranslationClient(endpoint=config['AzureTranslator']["EndPoint"], credential=credential)
    try:
        language = "zh-Hant"
        from_script = "Hant"
        to_script = "Latn"
        input_text_elements = [ InputTextItem(text = user_input) ]
        response = text_translator.transliterate(content = input_text_elements, language = language, from_script = from_script ,to_script = to_script)

        transliteration = response[0] if response else None
        if transliteration:
            return transliteration.text
        
    except HttpResponseError as exception:
        print(f"Error Code: {exception.error}")
        print(f"Message: {exception.error.message}")

def azure_transliterate_ja(user_input):
    credential = TranslatorCredential(config['AzureTranslator']["Key"], config['AzureTranslator']["Region"])
    text_translator = TextTranslationClient(endpoint=config['AzureTranslator']["EndPoint"], credential=credential)
    try:
        language = "ja"
        from_script = "Jpan"
        to_script = "Latn"
        input_text_elements = [ InputTextItem(text = user_input) ]
        response = text_translator.transliterate(content = input_text_elements, language = language, from_script = from_script ,to_script = to_script)

        transliteration = response[0] if response else None
        if transliteration:
            return transliteration.text
        
    except HttpResponseError as exception:
        print(f"Error Code: {exception.error}")
        print(f"Message: {exception.error.message}")
        
def azure_transliterate_ko(user_input):
    credential = TranslatorCredential(config['AzureTranslator']["Key"], config['AzureTranslator']["Region"])
    text_translator = TextTranslationClient(endpoint=config['AzureTranslator']["EndPoint"], credential=credential)
    try:
        language = "ko"
        from_script = "Kore"
        to_script = "Latn"
        input_text_elements = [ InputTextItem(text = user_input) ]
        response = text_translator.transliterate(content = input_text_elements, language = language, from_script = from_script ,to_script = to_script)

        transliteration = response[0] if response else None
        if transliteration:
            return transliteration.text


    except HttpResponseError as exception:
        print(f"Error Code: {exception.error}")
        print(f"Message: {exception.error.message}")



def azure_speech_hant(user_input):
    # The language of the voice that speaks.
    speech_config.speech_synthesis_voice_name = "zh-TW-YunJheNeural"
    file_name = "outputaudio_hant.wav"
    file_config = speechsdk.audio.AudioOutputConfig(filename="static/" + file_name)
    speech_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=file_config
    )

    # Receives a text from console input and synthesizes it to wave file.
    result = speech_synthesizer.speak_text_async(user_input).get()
    # Check result
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(
            "Speech synthesized for text [{}], and the audio was saved to [{}]".format(
                user_input, file_name
            )
        )
        audio_duration_hant = round(
            librosa.get_duration(path="static/outputaudio_hant.wav") * 1000
        )
        print(audio_duration_hant)
        return audio_duration_hant
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print("Error details: {}".format(cancellation_details.error_details))

def azure_speech_ja(user_input):
    # The language of the voice that speaks.
    speech_config.speech_synthesis_voice_name = "ja-JP-NanamiNeural"
    file_name = "outputaudio_ja.wav"
    file_config = speechsdk.audio.AudioOutputConfig(filename="static/" + file_name)
    speech_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=file_config
    )

    # Receives a text from console input and synthesizes it to wave file.
    result = speech_synthesizer.speak_text_async(user_input).get()
    # Check result
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(
            "Speech synthesized for text [{}], and the audio was saved to [{}]".format(
                user_input, file_name
            )
        )
        audio_duration_ja = round(
            librosa.get_duration(path="static/outputaudio_ja.wav") * 1000
        )
        print(audio_duration_ja)
        return audio_duration_ja
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print("Error details: {}".format(cancellation_details.error_details))

def azure_speech_ko(user_input):
    # The language of the voice that speaks.
    speech_config.speech_synthesis_voice_name = "ko-KR-InJoonNeural"
    file_name = "outputaudio_ko.wav"
    file_config = speechsdk.audio.AudioOutputConfig(filename="static/" + file_name)
    speech_synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=file_config
    )

    # Receives a text from console input and synthesizes it to wave file.
    result = speech_synthesizer.speak_text_async(user_input).get()
    # Check result
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(
            "Speech synthesized for text [{}], and the audio was saved to [{}]".format(
                user_input, file_name
            )
        )
        audio_duration_ko = round(
            librosa.get_duration(path="static/outputaudio_ko.wav") * 1000
        )
        print(audio_duration_ko)
        return audio_duration_ko
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print("Error details: {}".format(cancellation_details.error_details))

import requests
import json
def azure_custom_question_answer(question):
    url = "https://langauge-door05.cognitiveservices.azure.com/language/:query-knowledgebases?projectName=dfvdfsgv&api-version=2021-10-01&deploymentName=production"
    headers = {
        "Ocp-Apim-Subscription-Key": "1ecccb806612441ba02176ec9b250cf8",
        "Content-Type": "application/json"
    }
    payload = {
        "top": 1,
        "question": question,
        "includeUnstructuredSources": True,
        
        "answerSpanRequest": {
            "enable": True,
            "topAnswersWithSpan": 1
            
        },
            
        }
    
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code == 200:
        data = response.json()
        desired_answer = data['answers'][0]['answer']
        # Process and return the response data as needed
        print(data)
        return desired_answer
    
    else:
        return None

# Example usage
# question = "YOUR_QUESTION_HERE"
# response = azure_custom_question_answer(question)
# if response:
#     print(response)
# else:
#     print("Failed to get a response from the Azure service.")


if __name__ == "__main__":
    app.run()