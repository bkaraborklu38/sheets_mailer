# attachments/

Her maile eklenecek dosyayı (ör. sponsorluk dosyası PDF'i) bu klasöre koyun ve
`config.yaml` içindeki `gonderim.ek_dosya` satırına dosya yolunu yazın:

```yaml
gonderim:
  ek_dosya: "attachments/sponsorluk_dosyasi.pdf"
```

Ek göndermek istemiyorsanız `ek_dosya` değerini boş bırakın (`""`).

> Repo public ise buraya koyduğunuz dosya herkes tarafından görülebilir.
