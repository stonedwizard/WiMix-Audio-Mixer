#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>

#define SCREEN_W 128
#define SCREEN_H 64
#define TCA_ADDR 0x70
#define OLED_ADDR 0x3C

#define NUM_CH 5
#define LED_PIN 2
#define LEDS_PER_CHANNEL 12
#define NUM_LEDS (NUM_CH * LEDS_PER_CHANNEL)

#define LED_BRIGHTNESS 7          // начальная яркость (0-255)

const uint8_t tcaMap[NUM_CH] = {2, 3, 4, 5, 6};
const int adcPins[NUM_CH] = {6, 7, 4, 5, 15};

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
Adafruit_NeoPixel strip(NUM_LEDS, LED_PIN, NEO_GRB + NEO_KHZ800);

int levels[NUM_CH];

unsigned long lastLEDUpdate = 0;
unsigned long lastADCRead = 0;
unsigned long lastPCSend = 0;

uint8_t channelRole[NUM_CH] = {1,2,3,4,5};
float vuPos[NUM_CH] = {0,0,0,0,0};

// базовые цвета каналов
uint8_t chColor[NUM_CH][3] = {
  {0,255,0},     // reserve
  {0,160,255},   // mic
  {180,0,255},   // chat
  {255,120,0},   // game
  {0,255,80}     // music
};

uint8_t currentBrightness = LED_BRIGHTNESS;  // текущая яркость (будет меняться по команде)

void tcaSelect(uint8_t ch){
  Wire.beginTransmission(TCA_ADDR);
  Wire.write(1 << tcaMap[ch]);
  Wire.endTransmission();
}

// градиент канал → красный
uint32_t vuGradient(uint8_t ch, float p){
  p = constrain(p,0,1);
  float r1 = chColor[ch][0];
  float g1 = chColor[ch][1];
  float b1 = chColor[ch][2];

  float r = r1 + (255 - r1) * p;
  float g = g1 * (1.0 - p);
  float b = b1 * (1.0 - p);

  return strip.Color(r,g,b);
}

void drawIcon(uint8_t role){
  int cx=64,cy=26;
  if(role==5){
    display.fillCircle(cx-6,cy-6,4,SSD1306_WHITE);
    display.drawLine(cx-2,cy-10,cx-2,cy+6,SSD1306_WHITE);
    display.drawLine(cx-2,cy-10,cx+6,cy-14,SSD1306_WHITE);
  }
  else if(role==4){
    display.drawRoundRect(cx-18,cy-6,36,12,6,SSD1306_WHITE);
    display.fillCircle(cx-8,cy,2,SSD1306_WHITE);
    display.fillCircle(cx+8,cy,2,SSD1306_WHITE);
  }
  else if(role==3){
    display.drawRoundRect(cx-18,cy-10,36,16,6,SSD1306_WHITE);
    display.fillTriangle(cx-4,cy+6,cx+4,cy+6,cx,cy+12,SSD1306_WHITE);
  }
  else if(role==2){
    display.drawRoundRect(cx-6,cy-12,12,20,6,SSD1306_WHITE);
    display.drawLine(cx,cy+8,cx,cy+16,SSD1306_WHITE);
    display.drawLine(cx-6,cy+16,cx+6,cy+16,SSD1306_WHITE);
  }
  else{
    display.drawLine(cx-10,cy,cx+10,cy,SSD1306_WHITE);
    display.drawLine(cx,cy-10,cx,cy+10,SSD1306_WHITE);
  }
}

void drawDotBar(int level){
  int dots=12;
  int active=map(level,0,4095,0,dots);
  int y=54,startX=10,step=9;
  for(int i=0;i<dots;i++)
    if(i<active) display.fillCircle(startX+i*step,y,3,SSD1306_WHITE);
}

void drawChannel(int ch){
  tcaSelect(ch);
  display.clearDisplay();
  drawIcon(channelRole[ch]);
  drawDotBar(levels[ch]);
  display.display();
}

void updateLEDStrip(){
  if(millis()-lastLEDUpdate<10) return;

  for(int ch=0;ch<NUM_CH;ch++){
    if(levels[ch]<40) levels[ch]=0;

    float target=map(levels[ch],0,4095,0,(LEDS_PER_CHANNEL-1)*100)/100.0;
    float k = target > vuPos[ch] ? 1.0 : 0.35;
    vuPos[ch] += (target - vuPos[ch]) * k;

    int base=ch*LEDS_PER_CHANNEL;

    for(int i=0;i<LEDS_PER_CHANNEL;i++)
      strip.setPixelColor(base+i,0);

    int i=vuPos[ch];
    float frac=vuPos[ch]-i;

    uint32_t c = vuGradient(ch, vuPos[ch]/LEDS_PER_CHANNEL);

    uint8_t r=(c>>16)&255;
    uint8_t g=(c>>8)&255;
    uint8_t b=c&255;

    strip.setPixelColor(base+(LEDS_PER_CHANNEL-1-i),
      strip.Color(r*(1-frac),g*(1-frac),b*(1-frac)));

    if(i+1<LEDS_PER_CHANNEL){
      strip.setPixelColor(base+(LEDS_PER_CHANNEL-2-i),
        strip.Color(r*frac,g*frac,b*frac));
    }
  }

  strip.show();
  lastLEDUpdate=millis();
}

void readADCLevels(){
  if(millis()-lastADCRead<2) return;
  for(int i=0;i<NUM_CH;i++)
    levels[i]=analogRead(adcPins[i]);
  lastADCRead=millis();
}

void sendToPC(){
  if(millis()-lastPCSend<5) return;
  StaticJsonDocument<128> doc;
  for(int i=0;i<NUM_CH;i++)
    doc["f"+String(i+1)]=levels[i];
  serializeJson(doc,Serial);
  Serial.println();
  lastPCSend=millis();
}

// ========== НОВАЯ ФУНКЦИЯ: ОБРАБОТКА КОМАНД С PC ==========
void handleSerialCommands() {
  static String inputString = "";
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      // Получили полную строку JSON
      StaticJsonDocument<128> doc;
      DeserializationError error = deserializeJson(doc, inputString);
      if (!error) {
        const char* cmd = doc["cmd"];
        if (cmd && strcmp(cmd, "set_brightness") == 0) {
          int value = doc["value"] | currentBrightness;
          value = constrain(value, 0, 255);
          currentBrightness = value;
          strip.setBrightness(currentBrightness);
          // Можно отправить подтверждение (опционально)
          Serial.println("{\"status\":\"brightness_set\"}");
        }
        // Здесь можно добавить другие команды в будущем
      }
      inputString = "";
    } else {
      inputString += c;
    }
  }
}

void setup(){
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);

  for(int i=0;i<NUM_CH;i++){
    tcaSelect(i);
    display.begin(SSD1306_SWITCHCAPVCC,OLED_ADDR);
    display.clearDisplay();
    display.display();
  }

  strip.begin();
  strip.setBrightness(currentBrightness);   // устанавливаем сохранённую яркость
  strip.clear();
  strip.show();

  Serial.println("{\"status\":\"gradient_dot_ready\"}");
}

void loop(){
  readADCLevels();
  sendToPC();
  for(int i=0;i<NUM_CH;i++) drawChannel(i);
  updateLEDStrip();
  handleSerialCommands();   // <-- проверяем команды с PC
}