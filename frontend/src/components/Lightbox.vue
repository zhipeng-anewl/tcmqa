<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
import {
  lightbox,
  closeLightbox,
  selectLightboxImage,
} from '../stores/lightbox'

function onImgError(e) {
  e.target.style.display = 'none'
}

function onKeydown(e) {
  if (e.key === 'Escape') closeLightbox()
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div v-if="lightbox.visible" class="lightbox" @click.self="closeLightbox">
    <button class="lb-close" title="关闭" @click="closeLightbox">×</button>
    <div class="lb-main">
      <img id="lb-img" :src="lightbox.src" alt="" />
      <div class="lb-caption">
        {{ lightbox.name }} · <b>{{ lightbox.kindText }}</b>
        <template v-if="lightbox.id"> · {{ lightbox.id }}</template>
      </div>
    </div>
    <div v-if="lightbox.strip.length" class="lb-strip">
      <img
        v-for="(it, i) in lightbox.strip"
        :key="i"
        :src="it.thumb || it.url"
        :title="it.filename"
        :class="{ active: i === lightbox.activeIndex }"
        loading="lazy"
        @error="onImgError"
        @click="selectLightboxImage(i)"
      />
    </div>
  </div>
</template>
