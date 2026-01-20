#!/usr/bin/env node
/**
 * 🤖 Расширенный Telegram MCP на Node.js
 * Полный функционал: текст, голосовые, файлы, транскрипция, ElevenLabs
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import fs from 'fs/promises';
import path from 'path';
import fetch, { FormData } from 'node-fetch';
import { fileURLToPath } from 'url';
import { exec } from 'child_process';
import { promisify } from 'util';

// Определяем __dirname для ES modules
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const execAsync = promisify(exec);

// Пробуем загрузить .env файл ТОЛЬКО если токен НЕ передан через ENV
if (!process.env.TELEGRAM_BOT_TOKEN) {
  try {
    const envPath = path.join(__dirname, '.env');
    const envContent = await fs.readFile(envPath, 'utf8');
    envContent.split('\n').forEach(line => {
      const match = line.match(/^([^#][^=]+)=(.+)$/);
      if (match) {
        const [, key, value] = match;
        process.env[key.trim()] = value.trim();
      }
    });
  } catch (error) {
    // .env файл не обязателен
  }
}

// ========== КОНФИГУРАЦИЯ ==========
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || "YOUR_BOT_TOKEN_HERE";
const ASSEMBLYAI_API_KEY = process.env.ASSEMBLYAI_API_KEY;
const ELEVENLABS_API_KEY = process.env.ELEVENLABS_API_KEY;

// Проверяем что токен установлен
if (TELEGRAM_BOT_TOKEN === "YOUR_BOT_TOKEN_HERE") {
  console.error("❌ ОШИБКА: Токен бота не установлен!");
  console.error("Установите через: claude mcp add telegram node /path/to/telegram.js --env TELEGRAM_BOT_TOKEN=your_token");
  process.exit(1);
}

// Путь к Memory можно переопределить через переменную окружения
const MEMORY_DIR = process.env.MEMORY_DIR 
  ? path.resolve(process.env.MEMORY_DIR)
  : path.join(process.cwd(), "Memory");
const USERS_DIR = path.join(MEMORY_DIR, "people");
const STATE_FILE = path.join(MEMORY_DIR, "telegram_state.json");

// Создаём папки
await fs.mkdir(MEMORY_DIR, { recursive: true });
await fs.mkdir(USERS_DIR, { recursive: true });

// ========== УТИЛИТЫ ==========
class FileManager {
  static async ensureUserDirs(chatId) {
    const userDir = path.join(USERS_DIR, String(chatId));
    const filesDir = path.join(userDir, 'files');
    const voiceDir = path.join(filesDir, 'voice');
    const docsDir = path.join(filesDir, 'documents');
    const imagesDir = path.join(filesDir, 'images');
    
    await fs.mkdir(userDir, { recursive: true });
    await fs.mkdir(filesDir, { recursive: true });
    await fs.mkdir(voiceDir, { recursive: true });
    await fs.mkdir(docsDir, { recursive: true });
    await fs.mkdir(imagesDir, { recursive: true });
    
    return { userDir, filesDir, voiceDir, docsDir, imagesDir };
  }

  static async downloadFile(fileId, savePath) {
    try {
      // Получаем путь к файлу
      const fileResponse = await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getFile?file_id=${fileId}`);
      const fileData = await fileResponse.json();
      
      if (!fileData.ok) return null;
      
      // Скачиваем файл
      const fileUrl = `https://api.telegram.org/file/bot${TELEGRAM_BOT_TOKEN}/${fileData.result.file_path}`;
      const response = await fetch(fileUrl);
      const buffer = await response.buffer();
      
      await fs.writeFile(savePath, buffer);
      return savePath;
    } catch (error) {
      console.error('Ошибка загрузки файла:', error);
      return null;
    }
  }

  static async transcribeAudio(audioPath) {
    if (!ASSEMBLYAI_API_KEY) {
      return "⚠️ Транскрипция недоступна: нет ASSEMBLYAI_API_KEY";
    }

    try {
      // Загружаем файл в AssemblyAI
      const audioData = await fs.readFile(audioPath);
      const uploadResponse = await fetch('https://api.assemblyai.com/v2/upload', {
        method: 'POST',
        headers: {
          'authorization': ASSEMBLYAI_API_KEY,
          'content-type': 'application/octet-stream',
        },
        body: audioData
      });
      
      const uploadResult = await uploadResponse.json();
      
      // Запускаем транскрипцию
      const transcriptResponse = await fetch('https://api.assemblyai.com/v2/transcript', {
        method: 'POST',
        headers: {
          'authorization': ASSEMBLYAI_API_KEY,
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          audio_url: uploadResult.upload_url,
          language_code: 'ru'
        })
      });
      
      const transcriptResult = await transcriptResponse.json();
      const transcriptId = transcriptResult.id;
      
      // Ждём результат
      let attempts = 0;
      while (attempts < 30) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        const statusResponse = await fetch(`https://api.assemblyai.com/v2/transcript/${transcriptId}`, {
          headers: { 'authorization': ASSEMBLYAI_API_KEY }
        });
        
        const statusResult = await statusResponse.json();
        
        if (statusResult.status === 'completed') {
          return statusResult.text || '(Пустая транскрипция)';
        } else if (statusResult.status === 'error') {
          return `❌ Ошибка транскрипции: ${statusResult.error}`;
        }
        
        attempts++;
      }
      
      return "⏰ Таймаут транскрипции";
    } catch (error) {
      return `❌ Ошибка транскрипции: ${error.message}`;
    }
  }

  static async convertToMp3(inputPath, outputPath) {
    try {
      await execAsync(`ffmpeg -i "${inputPath}" -acodec mp3 "${outputPath}" -y`);
      return outputPath;
    } catch (error) {
      console.error('Ошибка конвертации в MP3:', error);
      return inputPath; // Возвращаем оригинальный файл
    }
  }
}

// ========== TELEGRAM КЛИЕНТ ==========
class TelegramClient {
  constructor() {
    this.apiUrl = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}`;
    this.lastUpdateId = 0;
    this.loadState();
  }

  async loadState() {
    try {
      const data = await fs.readFile(STATE_FILE, 'utf8');
      const state = JSON.parse(data);
      this.lastUpdateId = state.last_update_id || 0;
    } catch {
      this.lastUpdateId = 0;
    }
  }

  async saveState() {
    const state = {
      last_update_id: this.lastUpdateId,
      last_check: new Date().toISOString()
    };
    await fs.writeFile(STATE_FILE, JSON.stringify(state, null, 2));
  }

  async getUpdates() {
    try {
      const response = await fetch(`${this.apiUrl}/getUpdates?offset=${this.lastUpdateId + 1}&timeout=10`);
      const data = await response.json();
      
      if (data.result && data.result.length > 0) {
        this.lastUpdateId = data.result[data.result.length - 1].update_id;
        await this.saveState();
      }
      
      return data.result || [];
    } catch (error) {
      console.error('Ошибка получения обновлений:', error);
      return [];
    }
  }

  async sendMessage(chatId, text, retries = 3) {
    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const response = await fetch(`${this.apiUrl}/sendMessage`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chat_id: chatId,
            text: text,
            parse_mode: 'Markdown'
          })
        });
        
        if (response.ok) {
          return true;
        }
        
        // Логируем ошибку
        const errorText = await response.text();
        console.error(`[Telegram] Попытка ${attempt}/${retries} не удалась:`, response.status, errorText);
        
        // Ждем перед повторной попыткой
        if (attempt < retries) {
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        }
      } catch (error) {
        console.error(`[Telegram] Попытка ${attempt}/${retries} - ошибка сети:`, error.message);
        
        if (attempt < retries) {
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        }
      }
    }
    
    return false;
  }

  async sendVoice(chatId, voicePath, retries = 3) {
    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const voiceData = await fs.readFile(voicePath);
        const form = new FormData();
        form.append('chat_id', chatId);
        form.append('voice', voiceData, { filename: 'voice.ogg' });

        const response = await fetch(`${this.apiUrl}/sendVoice`, {
          method: 'POST',
          body: form
        });
        
        if (response.ok) {
          return true;
        }
        
        console.error(`[Telegram Voice] Попытка ${attempt}/${retries} не удалась:`, response.status);
        
        if (attempt < retries) {
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        }
      } catch (error) {
        console.error(`[Telegram Voice] Попытка ${attempt}/${retries} - ошибка:`, error.message);
        
        if (attempt < retries) {
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        }
      }
    }
    
    return false;
  }

  async sendDocument(chatId, filePath, retries = 3) {
    try {
      console.log(`📁 Отправка файла: ${filePath} в чат ${chatId}`);
      
      // Проверяем существование файла
      const stats = await fs.stat(filePath);
      console.log(`📊 Размер файла: ${stats.size} байт (${(stats.size / 1024 / 1024).toFixed(2)} MB)`);
      
      // Проверяем ограничение Telegram (50MB)
      if (stats.size > 50 * 1024 * 1024) {
        console.error('❌ Файл слишком большой для Telegram (>50MB)');
        return false;
      }
      
      const fileData = await fs.readFile(filePath);
      const fileName = path.basename(filePath);
      console.log(`📝 Имя файла: ${fileName}`);
      
      // Повторные попытки отправки
      for (let attempt = 1; attempt <= retries; attempt++) {
        try {
          const form = new FormData();
          form.append('chat_id', chatId);
          form.append('document', fileData, { filename: fileName });

          const response = await fetch(`${this.apiUrl}/sendDocument`, {
            method: 'POST',
            body: form
          });
          
          console.log(`🔍 Попытка ${attempt}/${retries} - Ответ API: ${response.status} ${response.statusText}`);
          
          if (response.ok) {
            console.log('✅ Файл успешно отправлен!');
            return true;
          }
          
          const errorText = await response.text();
          console.error(`❌ Попытка ${attempt}/${retries} не удалась:`, errorText);
          
          if (attempt < retries) {
            await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
          }
        } catch (sendError) {
          console.error(`[Telegram Doc] Попытка ${attempt}/${retries} - ошибка сети:`, sendError.message);
          
          if (attempt < retries) {
            await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
          }
        }
      }
      
      return false;
    } catch (error) {
      console.error('❌ Ошибка подготовки файла:', error.message);
      return false;
    }
  }
}

// ========== МЕНЕДЖЕР КОНТЕКСТА ==========
class ContextManager {
  static getUserDir(chatId) {
    return path.join(USERS_DIR, String(chatId));
  }

  static async saveMessage(chatId, message) {
    const userDir = this.getUserDir(chatId);
    await fs.mkdir(userDir, { recursive: true });
    
    const historyFile = path.join(userDir, 'telegram_history.jsonl');
    message.saved_at = new Date().toISOString();
    
    await fs.appendFile(historyFile, JSON.stringify(message) + '\n', 'utf8');
  }

  static async getHistory(chatId, limit = 20) {
    const historyFile = path.join(this.getUserDir(chatId), 'telegram_history.jsonl');
    
    try {
      const content = await fs.readFile(historyFile, 'utf8');
      const messages = content.trim().split('\n')
        .filter(line => line)
        .map(line => JSON.parse(line));
      
      return messages.slice(-limit);
    } catch {
      return [];
    }
  }

  static async getUserContext(userId, messageLimit = 50) {
    const userDir = this.getUserDir(userId);
    const context = {
      user_id: userId,
      user_dir: userDir,
      message_history: await this.getHistory(userId, messageLimit),
      files: await this.getUserFiles(userId)
    };
    
    return context;
  }

  static async getUserFiles(userId, fileType = 'all') {
    const { filesDir } = await FileManager.ensureUserDirs(userId);
    const files = [];
    
    try {
      const subDirs = ['voice', 'documents', 'images'];
      for (const subDir of subDirs) {
        if (fileType !== 'all' && fileType !== subDir) continue;
        
        const dirPath = path.join(filesDir, subDir);
        const dirFiles = await fs.readdir(dirPath);
        
        for (const file of dirFiles) {
          const filePath = path.join(dirPath, file);
          const stats = await fs.stat(filePath);
          files.push({
            name: file,
            type: subDir,
            path: filePath,
            size: stats.size,
            created: stats.birthtime.toISOString()
          });
        }
      }
    } catch (error) {
      console.error('Ошибка получения файлов:', error);
    }
    
    return files;
  }

  static async searchUserFiles(userId, searchQuery) {
    const files = await this.getUserFiles(userId);
    return files.filter(file => 
      file.name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }

  static async getFileContent(userId, fileName) {
    const files = await this.getUserFiles(userId);
    const file = files.find(f => f.name === fileName);
    
    if (!file) return null;
    
    try {
      // Для текстовых файлов возвращаем содержимое
      if (file.name.endsWith('.txt') || file.name.endsWith('.md')) {
        const content = await fs.readFile(file.path, 'utf8');
        return { ...file, content };
      }
      
      // Для остальных - только метаданные
      return file;
    } catch (error) {
      console.error('Ошибка чтения файла:', error);
      return null;
    }
  }
}

// ========== MCP СЕРВЕР ==========
const telegramClient = new TelegramClient();

const server = new Server(
  {
    name: "telegram-extended",
    version: "2.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Список инструментов
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "check_telegram_messages",
        description: "Проверить новые сообщения в Telegram (с поддержкой голосовых и файлов)",
        inputSchema: {
          type: "object",
          properties: {},
        },
      },
      {
        name: "send_telegram_message",
        description: "Отправить текстовое сообщение в Telegram",
        inputSchema: {
          type: "object",
          properties: {
            chat_id: { type: "integer", description: "ID чата" },
            text: { type: "string", description: "Текст сообщения" }
          },
          required: ["chat_id", "text"]
        },
      },
      {
        name: "send_multiple_messages",
        description: "Отправить несколько сообщений подряд (как в живом чате). Используй это вместо одного длинного сообщения!",
        inputSchema: {
          type: "object",
          properties: {
            chat_id: { type: "integer", description: "ID чата" },
            messages: {
              type: "array",
              items: { type: "string" },
              description: "Массив коротких сообщений для отправки по очереди"
            },
            delay_ms: { type: "integer", description: "Задержка между сообщениями в мс", default: 500 }
          },
          required: ["chat_id", "messages"]
        },
      },
      {
        name: "get_user_history",
        description: "Получить историю переписки",
        inputSchema: {
          type: "object",
          properties: {
            chat_id: { type: "integer", description: "ID чата" },
            limit: { type: "integer", description: "Количество сообщений", default: 20 }
          },
          required: ["chat_id"]
        },
      },
      {
        name: "get_user_context",
        description: "Получить полный контекст пользователя (история + файлы)",
        inputSchema: {
          type: "object",
          properties: {
            user_id: { type: "integer", description: "ID пользователя" },
            message_limit: { type: "integer", description: "Лимит сообщений", default: 50 }
          },
          required: ["user_id"]
        },
      },
      {
        name: "list_user_files",
        description: "Список файлов пользователя",
        inputSchema: {
          type: "object",
          properties: {
            user_id: { type: "integer", description: "ID пользователя" },
            file_type: { type: "string", description: "Тип файлов: all, voice, documents, images", default: "all" }
          },
          required: ["user_id"]
        },
      },
      {
        name: "get_file_content",
        description: "Получить содержимое файла пользователя",
        inputSchema: {
          type: "object",
          properties: {
            user_id: { type: "integer", description: "ID пользователя" },
            file_name: { type: "string", description: "Имя файла" }
          },
          required: ["user_id", "file_name"]
        },
      },
      {
        name: "search_user_files",
        description: "Поиск файлов пользователя по имени",
        inputSchema: {
          type: "object",
          properties: {
            user_id: { type: "integer", description: "ID пользователя" },
            search_query: { type: "string", description: "Поисковый запрос" }
          },
          required: ["user_id", "search_query"]
        },
      },
      {
        name: "send_file",
        description: "Отправить файл в Telegram",
        inputSchema: {
          type: "object",
          properties: {
            chat_id: { type: "integer", description: "ID чата" },
            file_path: { type: "string", description: "Путь к файлу" }
          },
          required: ["chat_id", "file_path"]
        },
      },
      {
        name: "send_voice",
        description: "Отправить голосовое сообщение в Telegram",
        inputSchema: {
          type: "object",
          properties: {
            chat_id: { type: "integer", description: "ID чата" },
            voice_file: { type: "string", description: "Путь к голосовому файлу" }
          },
          required: ["chat_id", "voice_file"]
        },
      },
      {
        name: "test_file_send",
        description: "Тестовая отправка файла с созданием тестового файла",
        inputSchema: {
          type: "object",
          properties: {
            chat_id: { type: "integer", description: "ID чата" },
            test_content: {
              type: "string",
              description: "Содержимое тестового файла",
              default: "Тестовый файл от LIVE_AI"
            }
          },
          required: ["chat_id"]
        },
      },
      {
        name: "set_message_reaction",
        description: "Поставить реакцию (эмодзи) под сообщением в Telegram",
        inputSchema: {
          type: "object",
          properties: {
            chat_id: { type: "integer", description: "ID чата" },
            message_id: { type: "integer", description: "ID сообщения" },
            emoji: { type: "string", description: "Эмодзи реакции (👍❤️🔥😂🤔👏🎉💯)", default: "❤️" }
          },
          required: ["chat_id", "message_id"]
        },
      }
    ],
  };
});

// Обработка вызовов
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "check_telegram_messages") {
    const updates = await telegramClient.getUpdates();
    
    if (updates.length === 0) {
      return {
        content: [{
          type: "text",
          text: "📭 Новых сообщений нет"
        }]
      };
    }

    const results = [];
    for (const update of updates) {
      if (!update.message) continue;
      
      const msg = update.message;
      const messageData = {
        chat_id: msg.chat.id,
        message_id: msg.message_id,
        user_name: msg.from.first_name || 'Unknown',
        user_id: msg.from.id,
        timestamp: new Date(msg.date * 1000).toISOString(),
        type: 'text',
        text: msg.text || '[Не текстовое сообщение]'
      };

      // Обработка голосовых сообщений
      if (msg.voice) {
        const { voiceDir } = await FileManager.ensureUserDirs(msg.chat.id);
        const fileName = `voice_${msg.message_id}.ogg`;
        const filePath = path.join(voiceDir, fileName);
        
        const downloadedPath = await FileManager.downloadFile(msg.voice.file_id, filePath);
        if (downloadedPath) {
          // Конвертируем в MP3 для лучшей совместимости
          const mp3Path = path.join(voiceDir, `voice_${msg.message_id}.mp3`);
          const actualAudioPath = await FileManager.convertToMp3(downloadedPath, mp3Path);
          
          // Транскрибируем (используем результат конвертации - либо .mp3, либо .ogg)
          const transcription = await FileManager.transcribeAudio(actualAudioPath);
          
          messageData.type = 'voice';
          messageData.text = `[Голосовое сообщение]`;
          messageData.transcription = transcription;
          messageData.voice_file = actualAudioPath;
          messageData.duration = msg.voice.duration;
        }
      }
      
      // Обработка документов
      if (msg.document) {
        const { docsDir } = await FileManager.ensureUserDirs(msg.chat.id);
        const fileName = msg.document.file_name || `document_${msg.message_id}`;
        const filePath = path.join(docsDir, fileName);
        
        const downloadedPath = await FileManager.downloadFile(msg.document.file_id, filePath);
        if (downloadedPath) {
          messageData.type = 'document';
          messageData.text = `[Документ: ${fileName}]`;
          messageData.file_name = fileName;
          messageData.file_path = downloadedPath;
          messageData.file_size = msg.document.file_size;
        }
      }
      
      // Обработка фотографий
      if (msg.photo && msg.photo.length > 0) {
        const { imagesDir } = await FileManager.ensureUserDirs(msg.chat.id);
        const photo = msg.photo[msg.photo.length - 1]; // Берём наибольшее разрешение
        const fileName = `photo_${msg.message_id}.jpg`;
        const filePath = path.join(imagesDir, fileName);
        
        const downloadedPath = await FileManager.downloadFile(photo.file_id, filePath);
        if (downloadedPath) {
          messageData.type = 'photo';
          messageData.text = msg.caption || '[Фотография]';
          messageData.file_name = fileName;
          messageData.file_path = downloadedPath;
        }
      }
      
      await ContextManager.saveMessage(msg.chat.id, messageData);
      results.push(messageData);
    }

    return {
      content: [{
        type: "text",
        text: `📬 Получено сообщений: ${results.length}\n\n${JSON.stringify(results, null, 2)}`
      }]
    };
  }

  if (name === "send_telegram_message") {
    const success = await telegramClient.sendMessage(args.chat_id, args.text);
    
    if (success) {
      await ContextManager.saveMessage(args.chat_id, {
        chat_id: args.chat_id,
        text: args.text,
        type: 'sent',
        timestamp: new Date().toISOString()
      });
      
      return {
        content: [{
          type: "text",
          text: `✅ Сообщение отправлено в чат ${args.chat_id}`
        }]
      };
    }
    
    return {
      content: [{
        type: "text",
        text: "❌ Ошибка отправки сообщения"
      }]
    };
  }

  if (name === "send_multiple_messages") {
    const { chat_id, messages, delay_ms = 500 } = args;
    const results = [];

    for (let i = 0; i < messages.length; i++) {
      const text = messages[i];
      const success = await telegramClient.sendMessage(chat_id, text);

      if (success) {
        await ContextManager.saveMessage(chat_id, {
          chat_id: chat_id,
          text: text,
          type: 'sent',
          timestamp: new Date().toISOString()
        });
        results.push(`✅ ${i + 1}: "${text.substring(0, 30)}..."`);
      } else {
        results.push(`❌ ${i + 1}: Ошибка`);
      }

      // Задержка между сообщениями (кроме последнего)
      if (i < messages.length - 1 && delay_ms > 0) {
        await new Promise(resolve => setTimeout(resolve, delay_ms));
      }
    }

    return {
      content: [{
        type: "text",
        text: `📨 Отправлено ${messages.length} сообщений:\n${results.join('\n')}`
      }]
    };
  }

  if (name === "get_user_history") {
    const history = await ContextManager.getHistory(args.chat_id, args.limit || 20);
    const userDir = ContextManager.getUserDir(args.chat_id);
    
    if (history.length === 0) {
      return {
        content: [{
          type: "text",
          text: `📜 История чата ${args.chat_id} пуста`
        }]
      };
    }
    
    // Форматируем историю в читаемом виде
    const formattedHistory = history.map(msg => {
      const timestamp = new Date(msg.timestamp || msg.saved_at).toLocaleString('ru-RU');
      const sender = msg.type === 'sent' ? 'Бот' : (msg.user_name || 'Пользователь');
      let text = msg.text;
      
      // Добавляем транскрипцию для голосовых
      if (msg.transcription) {
        text += `\n📝 Транскрипция: ${msg.transcription}`;
      }
      
      return `[${timestamp}] ${sender}: ${text}`;
    }).join('\n');
    
    return {
      content: [{
        type: "text",
        text: `📜 История чата ${args.chat_id} (${history.length} сообщений)\n📁 Сохранено в: ${userDir}\n\n${formattedHistory}`
      }]
    };
  }

  if (name === "get_user_context") {
    const context = await ContextManager.getUserContext(args.user_id, args.message_limit);
    return {
      content: [{
        type: "text",
        text: `👤 Контекст пользователя ${args.user_id}\n\n${JSON.stringify(context, null, 2)}`
      }]
    };
  }

  if (name === "list_user_files") {
    const files = await ContextManager.getUserFiles(args.user_id, args.file_type);
    return {
      content: [{
        type: "text",
        text: `📁 Файлы пользователя ${args.user_id} (${files.length} файлов)\n\n${JSON.stringify(files, null, 2)}`
      }]
    };
  }

  if (name === "get_file_content") {
    const file = await ContextManager.getFileContent(args.user_id, args.file_name);
    if (!file) {
      return {
        content: [{
          type: "text",
          text: `❌ Файл '${args.file_name}' не найден у пользователя ${args.user_id}`
        }]
      };
    }
    
    return {
      content: [{
        type: "text",
        text: `📄 Файл: ${args.file_name}\n\n${JSON.stringify(file, null, 2)}`
      }]
    };
  }

  if (name === "search_user_files") {
    const files = await ContextManager.searchUserFiles(args.user_id, args.search_query);
    return {
      content: [{
        type: "text",
        text: `🔍 Поиск "${args.search_query}" у пользователя ${args.user_id}\nНайдено: ${files.length} файлов\n\n${JSON.stringify(files, null, 2)}`
      }]
    };
  }

  if (name === "send_file") {
    console.log(`📤 MCP send_file: chat_id=${args.chat_id}, file_path=${args.file_path}`);
    
    // Проверяем параметры
    if (!args.chat_id || !args.file_path) {
      return {
        content: [{
          type: "text",
          text: "❌ Не указан chat_id или file_path"
        }]
      };
    }
    
    try {
      // Проверяем существование файла
      await fs.access(args.file_path);
      
      const success = await telegramClient.sendDocument(args.chat_id, args.file_path);
      
      return {
        content: [{
          type: "text",
          text: success ? `✅ Файл отправлен в чат ${args.chat_id}` : "❌ Ошибка отправки файла - проверьте логи"
        }]
      };
    } catch (error) {
      console.error('❌ Ошибка в MCP send_file:', error.message);
      return {
        content: [{
          type: "text",
          text: `❌ Ошибка: ${error.message}. Проверьте что файл существует: ${args.file_path}`
        }]
      };
    }
  }

  if (name === "send_voice") {
    const success = await telegramClient.sendVoice(args.chat_id, args.voice_file);
    return {
      content: [{
        type: "text",
        text: success ? `🎤 Голосовое сообщение отправлено в чат ${args.chat_id}` : "❌ Ошибка отправки голосового"
      }]
    };
  }

  if (name === "test_file_send") {
    console.log(`🧪 Тестовая отправка файла в чат ${args.chat_id}`);
    
    try {
      // Создаем тестовый файл
      const testContent = args.test_content || 'Тестовый файл от LIVE_AI';
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      const testFilePath = path.join('/tmp', `test_${timestamp}.txt`);
      
      await fs.writeFile(testFilePath, testContent, 'utf8');
      console.log(`📄 Создан тестовый файл: ${testFilePath}`);
      
      // Отправляем файл
      const success = await telegramClient.sendDocument(args.chat_id, testFilePath);
      
      // Удаляем тестовый файл
      try {
        await fs.unlink(testFilePath);
        console.log(`🗑️ Тестовый файл удален`);
      } catch (unlinkError) {
        console.warn(`⚠️ Не удалось удалить тестовый файл: ${unlinkError.message}`);
      }
      
      return {
        content: [{
          type: "text",
          text: success 
            ? `✅ Тестовый файл успешно отправлен в чат ${args.chat_id}! 📁`
            : `❌ Ошибка отправки тестового файла - проверьте логи`
        }]
      };
    } catch (error) {
      console.error('❌ Ошибка в test_file_send:', error.message);
      return {
        content: [{
          type: "text",
          text: `❌ Ошибка тестовой отправки: ${error.message}`
        }]
      };
    }
  }

  if (name === "set_message_reaction") {
    const { chat_id, message_id, emoji = "❤️" } = args;
    try {
      const response = await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setMessageReaction`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chat_id: chat_id,
          message_id: message_id,
          reaction: [{ type: "emoji", emoji: emoji }]
        })
      });
      const result = await response.json();

      if (result.ok) {
        return {
          content: [{
            type: "text",
            text: `${emoji} Реакция поставлена!`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `❌ Ошибка: ${result.description}`
          }]
        };
      }
    } catch (error) {
      return {
        content: [{
          type: "text",
          text: `❌ Ошибка реакции: ${error.message}`
        }]
      };
    }
  }

  throw new Error(`Неизвестная команда: ${name}`);
});

// ========== ЗАПУСК ==========
async function main() {
  console.log('🚀 Запуск расширенного Telegram MCP');
  console.log(`🔑 Токен бота: ...${TELEGRAM_BOT_TOKEN.slice(-10)}`);
  console.log(`📁 Данные сохраняются в: ${MEMORY_DIR}`);
  console.log(`👥 Пользователи в: ${USERS_DIR}`);
  console.log(`🎤 AssemblyAI: ${ASSEMBLYAI_API_KEY ? '✅' : '❌'}`);
  console.log(`🗣️ ElevenLabs: ${ELEVENLABS_API_KEY ? '✅' : '❌'}`);
  
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);