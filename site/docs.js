// The documentation tab: search over the generated pages (search.json), and the page list that folds away on a phone.
(function () {
  var box = document.getElementById("q"), list = document.getElementById("hits"), side = document.querySelector(".sidebar");
  if (side && matchMedia("(max-width: 860px)").matches) side.open = false;
  if (!box || !list) return;
  var index = null;

  function snippet(text, words) {
    var low = text.toLowerCase(), at = low.indexOf(words[0]);
    var from = Math.max(0, at - 50);
    return (from ? "…" : "") + text.slice(from, from + 150) + "…";
  }
  function show(items, words) {
    list.textContent = "";
    items.slice(0, 12).forEach(function (it) {
      var li = document.createElement("li"), a = document.createElement("a"), small = document.createElement("small");
      a.href = it.url; a.textContent = it.title;
      small.textContent = snippet(it.text, words);
      li.appendChild(a); li.appendChild(small); list.appendChild(li);
    });
    if (!items.length) { var none = document.createElement("li"); none.className = "dim"; none.textContent = "Nothing found."; list.appendChild(none); }
    list.hidden = false;
    if (side) side.hidden = true;
  }
  function search() {
    var words = box.value.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) { list.hidden = true; if (side) side.hidden = false; return; }
    var found = index.map(function (it) {
      var title = it.title.toLowerCase(), text = it.text.toLowerCase(), score = 0;
      for (var i = 0; i < words.length; i++) {
        if (text.indexOf(words[i]) < 0 && title.indexOf(words[i]) < 0) return null;   // every word has to match
        score += (title.indexOf(words[i]) >= 0 ? 10 : 0) + 1;
      }
      return { it: it, score: score };
    }).filter(Boolean).sort(function (a, b) { return b.score - a.score; });
    show(found.map(function (f) { return f.it; }), words);
  }
  box.addEventListener("input", function () {
    if (index) return search();
    fetch("search.json").then(function (r) { return r.json(); }).then(function (data) { index = data; search(); })
      .catch(function () { list.hidden = false; list.textContent = "Search is not available right now."; });
  });
})();
