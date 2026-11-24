export function brandImage(variant = "mark") {
  const image = document.createElement("img");
  const wordmark = variant === "wordmark";
  image.className = wordmark ? "simson-wordmark" : "simson-mark";
  image.src = new URL(wordmark ? "brand/logo.png" : "brand/icon.png", import.meta.url).href;
  image.alt = wordmark ? "Simson by Architech Labs" : "";
  image.width = wordmark ? 132 : 34;
  image.height = wordmark ? 32 : 34;
  return image;
}
