// ============================================
// 每日互助 - 交互增强脚本
// ============================================

document.addEventListener('DOMContentLoaded', function() {

  // === 主题切换 ===
  const themeToggle = document.getElementById('themeToggle');
  const html = document.documentElement;
  const currentTheme = localStorage.getItem('theme') || 'dark';

  if (currentTheme === 'light') {
    html.setAttribute('data-theme', 'light');
  } else {
    html.removeAttribute('data-theme');
  }

  if (themeToggle) {
    themeToggle.addEventListener('click', function() {
      const isLight = html.getAttribute('data-theme') === 'light';
      if (isLight) {
        html.removeAttribute('data-theme');
        localStorage.setItem('theme', 'dark');
      } else {
        html.setAttribute('data-theme', 'light');
        localStorage.setItem('theme', 'light');
      }
      this.style.transform = 'scale(0.92)';
      setTimeout(() => { this.style.transform = ''; }, 180);
    });
  }

  // === 移动端菜单 ===
  const hamburger = document.getElementById('menuToggle') || document.querySelector('.hamburger');
  const navLinks = document.querySelector('.nav-links');

  if (hamburger && navLinks) {
    hamburger.addEventListener('click', function(e) {
      e.stopPropagation();
      navLinks.classList.toggle('open');
      const icon = this.querySelector('i');
      if (icon) {
        icon.classList.toggle('fa-bars');
        icon.classList.toggle('fa-xmark');
      }
    });

    document.addEventListener('click', function(e) {
      if (!hamburger.contains(e.target) && !navLinks.contains(e.target)) {
        navLinks.classList.remove('open');
        const icon = hamburger.querySelector('i');
        if (icon) {
          icon.classList.remove('fa-xmark');
          icon.classList.add('fa-bars');
        }
      }
    });
  }

  // === Flash 消息自动消失 ===
  const flashes = document.querySelectorAll('.flash');
  flashes.forEach(function(flash, index) {
    // 点击关闭
    flash.style.cursor = 'pointer';
    flash.addEventListener('click', function() {
      this.style.opacity = '0';
      this.style.transform = 'translateY(-8px)';
      setTimeout(() => this.remove(), 300);
    });

    // 5秒后自动消失
    setTimeout(function() {
      if (flash.parentNode) {
        flash.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
        flash.style.opacity = '0';
        flash.style.transform = 'translateY(-8px)';
        setTimeout(() => flash.remove(), 500);
      }
    }, 5000 + index * 500);
  });

  // === 滚动显示动画 (Reveal) ===
  const reveals = document.querySelectorAll('.reveal');
  if (reveals.length > 0) {
    const revealObserver = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    reveals.forEach(function(el) { revealObserver.observe(el); });
  }

  // === 卡片悬停效果增强 ===
  const featureCards = document.querySelectorAll('.card.feature');
  featureCards.forEach(function(card) {
    card.addEventListener('mouseenter', function() {
      this.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
    });
  });

  // === 返回顶部按钮 ===
  const backToTop = document.querySelector('.back-to-top');
  if (backToTop) {
    window.addEventListener('scroll', function() {
      if (window.scrollY > 400) {
        backToTop.classList.add('show');
      } else {
        backToTop.classList.remove('show');
      }
    }, { passive: true });

    backToTop.addEventListener('click', function() {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // === 导航栏滚动效果 ===
  const header = document.querySelector('.site-header');
  if (header) {
    let lastScroll = 0;
    window.addEventListener('scroll', function() {
      const currentScroll = window.scrollY;
      if (currentScroll > 60) {
        header.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.15)';
      } else {
        header.style.boxShadow = '';
      }
      lastScroll = currentScroll;
    }, { passive: true });
  }

});

// === 平滑滚动 ===
document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
  anchor.addEventListener('click', function(e) {
    const href = this.getAttribute('href');
    if (href === '#') return;
    const target = document.querySelector(href);
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

// === 按钮加载动画 ===
document.querySelectorAll('form .btn[type="submit"]').forEach(function(button) {
  button.closest('form').addEventListener('submit', function() {
    if (!button.classList.contains('loading')) {
      button.classList.add('loading');
    }
  });
});
