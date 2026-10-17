/*
Copyright (c) 2013-2019 Ivan Nikulin (ifaaan@gmail.com, https://github.com/inikulin)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
*/
// Streaming form of parse5 8's MIT-licensed serializer. The traversal and
// escaping match parse5; only writes replace whole-document concatenation.
import { html, defaultTreeAdapter } from 'parse5';
import { escapeText, escapeAttribute } from 'entities/escape';
import { Buffer } from 'node:buffer';
const { TAG_NAMES: $, NS, hasUnescapedText } = html;

/** Encode a string stream as if Buffer.from(allChunksJoined, 'utf8').
 *
 * The serializer can emit adjacent text nodes separately. Retain only a final
 * high surrogate so a following low surrogate is encoded as the original code
 * point. An unmatched final high surrogate is flushed using Node's ordinary
 * replacement semantics. No complete document string is accumulated.
 */
export function createUtf8Sink(writeBuffer) {
    if (typeof writeBuffer !== 'function') throw new TypeError('A byte sink is required');
    let pending = '', ended = false;
    return {
        write(chunk) {
            if (ended) throw new Error('UTF-8 sink is closed');
            if (typeof chunk !== 'string') throw new TypeError('UTF-8 sink requires string chunks');
            if (!chunk.length) return;
            let text = pending + chunk;
            pending = '';
            const last = text.charCodeAt(text.length - 1);
            if (last >= 0xD800 && last <= 0xDBFF) {
                pending = text.slice(-1);
                text = text.slice(0, -1);
            }
            if (text.length) writeBuffer(Buffer.from(text, 'utf8'));
        },
        end() {
            if (ended) throw new Error('UTF-8 sink is closed');
            ended = true;
            if (pending) {
                const last = pending;
                pending = '';
                writeBuffer(Buffer.from(last, 'utf8'));
            }
        },
    };
}

export function serializeToSink(node, options, write) {
// Sets
const VOID_ELEMENTS = new Set([
    $.AREA,
    $.BASE,
    $.BASEFONT,
    $.BGSOUND,
    $.BR,
    $.COL,
    $.EMBED,
    $.FRAME,
    $.HR,
    $.IMG,
    $.INPUT,
    $.KEYGEN,
    $.LINK,
    $.META,
    $.PARAM,
    $.SOURCE,
    $.TRACK,
    $.WBR,
]);
function isVoidElement(node, options) {
    return (options.treeAdapter.isElementNode(node) &&
        options.treeAdapter.getNamespaceURI(node) === NS.HTML &&
        VOID_ELEMENTS.has(options.treeAdapter.getTagName(node)));
}
const defaultOpts = { treeAdapter: defaultTreeAdapter, scriptingEnabled: true };
/**
 * Serializes an AST node to an HTML string.
 *
 * @example
 *
 * ```js
 * const parse5 = require('parse5');
 *
 * const document = parse5.parse('<!DOCTYPE html><html><head></head><body>Hi there!</body></html>');
 *
 * // Serializes a document.
 * const html = parse5.serialize(document);
 *
 * // Serializes the <html> element content.
 * const str = parse5.serialize(document.childNodes[1]);
 *
 * console.log(str); //> '<head></head><body>Hi there!</body>'
 * ```
 *
 * @param node Node to serialize.
 * @param options Serialization options.
 */
function serialize(node, options) {
    const opts = { ...defaultOpts, ...options };
    if (isVoidElement(node, opts)) {
        return '';
    }
    return serializeChildNodes(node, opts);
}
/**
 * Serializes an AST element node to an HTML string, including the element node.
 *
 * @example
 *
 * ```js
 * const parse5 = require('parse5');
 *
 * const document = parse5.parseFragment('<div>Hello, <b>world</b>!</div>');
 *
 * // Serializes the <div> element.
 * const str = parse5.serializeOuter(document.childNodes[0]);
 *
 * console.log(str); //> '<div>Hello, <b>world</b>!</div>'
 * ```
 *
 * @param node Node to serialize.
 * @param options Serialization options.
 */
function serializeOuter(node, options) {
    const opts = { ...defaultOpts, ...options };
    return serializeNode(node, opts);
}
function serializeChildNodes(parentNode, options) {
    // Stream child output using the exact dependency traversal.
    // Get container of the child nodes
    const container = options.treeAdapter.isElementNode(parentNode) &&
        options.treeAdapter.getTagName(parentNode) === $.TEMPLATE &&
        options.treeAdapter.getNamespaceURI(parentNode) === NS.HTML
        ? options.treeAdapter.getTemplateContent(parentNode)
        : parentNode;
    const childNodes = options.treeAdapter.getChildNodes(container);
    if (childNodes) {
        for (const currentNode of childNodes) {
            serializeNode(currentNode, options);
        }
    }
    return '';
}
function serializeNode(node, options) {
    if (options.treeAdapter.isElementNode(node)) {
        return serializeElement(node, options);
    }
    if (options.treeAdapter.isTextNode(node)) {
        write(serializeTextNode(node, options)); return;
    }
    if (options.treeAdapter.isCommentNode(node)) {
        write(serializeCommentNode(node, options)); return;
    }
    if (options.treeAdapter.isDocumentTypeNode(node)) {
        write(serializeDocumentTypeNode(node, options)); return;
    }
    // Return an empty string for unknown nodes
    return '';
}
function serializeElement(node, options) {
    const tn = options.treeAdapter.getTagName(node);
    write(`<${tn}${serializeAttributes(node, options)}>`);
    if (!isVoidElement(node, options)) { serializeChildNodes(node, options); write(`</${tn}>`); }
}
function serializeAttributes(node, { treeAdapter }) {
    let html = '';
    for (const attr of treeAdapter.getAttrList(node)) {
        html += ' ';
        if (attr.namespace) {
            switch (attr.namespace) {
                case NS.XML: {
                    html += `xml:${attr.name}`;
                    break;
                }
                case NS.XMLNS: {
                    if (attr.name !== 'xmlns') {
                        html += 'xmlns:';
                    }
                    html += attr.name;
                    break;
                }
                case NS.XLINK: {
                    html += `xlink:${attr.name}`;
                    break;
                }
                default: {
                    html += `${attr.prefix}:${attr.name}`;
                }
            }
        }
        else {
            html += attr.name;
        }
        html += `="${escapeAttribute(attr.value)}"`;
    }
    return html;
}
function serializeTextNode(node, options) {
    const { treeAdapter } = options;
    const content = treeAdapter.getTextNodeContent(node);
    const parent = treeAdapter.getParentNode(node);
    const parentTn = parent && treeAdapter.isElementNode(parent) && treeAdapter.getTagName(parent);
    return parentTn &&
        treeAdapter.getNamespaceURI(parent) === NS.HTML &&
        hasUnescapedText(parentTn, options.scriptingEnabled)
        ? content
        : escapeText(content);
}
function serializeCommentNode(node, { treeAdapter }) {
    return `<!--${treeAdapter.getCommentNodeContent(node)}-->`;
}
function serializeDocumentTypeNode(node, { treeAdapter }) {
    return `<!DOCTYPE ${treeAdapter.getDocumentTypeNodeName(node)}>`;
}

serialize(node,options);
}
