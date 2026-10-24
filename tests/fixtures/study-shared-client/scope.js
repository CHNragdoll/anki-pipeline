(function () {
  'use strict';
  var key = 'web-study:scope:v1';
  window.StudyScope = {
    read: function () { try { var value = JSON.parse(localStorage.getItem(key) || '{}'); return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; } catch (_) { return {}; } },
    write: function (book, deck) { try { var value = this.read(); value.book = book; value.decks = value.decks && typeof value.decks === 'object' && !Array.isArray(value.decks) ? value.decks : {}; value.decks[book] = deck; localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} },
    deck: function (book, books) { var value = this.read(); var choice = value.decks && value.decks[book]; var item = books.find(function (entry) { return entry.id === book; }); return item && item.decks.some(function (entry) { return String(entry.id) === choice; }) ? choice : 'all'; },
    label: function (item, deck) { var scope = item.decks.find(function (entry) { return String(entry.id) === deck; }); return scope ? [scope.unit, scope.lesson || scope.name].filter(Boolean).join(' · ') : '全部范围'; },
    shortName: function (item) { return ({liu:'2027 刘晓艳词汇',redbook:'2026 红宝书',redbook2027:'2027 红宝书'})[item.id] || item.name; }
  };
}());
