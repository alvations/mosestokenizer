# -*- coding: utf-8 -*-

from __future__ import print_function

import codecs
import re
from collections import defaultdict, Counter
try: # Python3
    from itertools import zip_longest
except ImportError: # Python2
    from itertools import izip_longest as zip_longest

from six import text_type

from sacremoses.corpus import Perluniprops

perluniprops = Perluniprops()


def grouper(iterable, n, fillvalue=None):
    """Collect data into fixed-length chunks or blocks
    from https://stackoverflow.com/a/16789869/610569
    """
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


class MosesTruecaser(object):
    """
    This is a Python port of the Moses Truecaser from
    https://github.com/moses-smt/mosesdecoder/blob/master/scripts/recaser/train-truecaser.perl
    https://github.com/moses-smt/mosesdecoder/blob/master/scripts/recaser/truecase.perl
    """
    # Perl Unicode Properties character sets.
    Lowercase_Letter = text_type(''.join(perluniprops.chars('Lowercase_Letter')))
    Uppercase_Letter = text_type(''.join(perluniprops.chars('Uppercase_Letter')))
    Titlecase_Letter = text_type(''.join(perluniprops.chars('Uppercase_Letter')))

    def __init__(self, load_from=None, is_asr=None):
        """
        :param load_from:
        :type load_from:

        :param is_asr: A flag to indicate that model is for ASR. ASR input has
            no case, make sure it is lowercase, and make sure known are cased
            eg. 'i' to be uppercased even if i is known.
        :type is_asr: bool
        """
        # Initialize the object.
        super(MosesTruecaser, self).__init__()
        # Initialize the language specific nonbreaking prefixes.
        self.SKIP_LETTERS_REGEX = re.compile(u"[{}{}{}]".format(
                                                self.Lowercase_Letter,
                                                self.Uppercase_Letter,
                                                self.Titlecase_Letter)
                                            )

        self.XML_SPLIT_REGX = re.compile("(<.*(?<=>))(.*)((?=</)[^>]*>)")

        self.SENT_END = {".", ":", "?", "!"}
        self.DELAYED_SENT_START = {"(", "[", "\"", "'", "&apos;", "&quot;", "&#91;", "&#93;"}

        self.is_asr = is_asr
        if load_from:
            self.model = self._load_model(load_from)

    def learn_truecase_weights(self, tokens, possibly_use_first_token=False):
        """
        This function checks through each tokens in a sentence and returns the
        appropriate weight of each surface token form.
        """
        # Keep track of first words in the sentence(s) of the line.
        is_first_word = True
        for i, token in enumerate(tokens):
            # Skip XML tags.
            if re.search(r"(<\S[^>]*>)", token):
                continue
            # Skip if sentence start symbols.
            elif token in self.DELAYED_SENT_START:
                continue

            # Resets the `is_first_word` after seeing sent end symbols.
            if not is_first_word and token in self.SENT_END:
                is_first_word = True
                continue
            # Skips words with nothing to case.
            if not self.SKIP_LETTERS_REGEX.search(token):
                is_first_word = False
                continue

            # If it's not the first word,
            # then set the current word weight to 1.
            current_word_weight = 0
            if not is_first_word:
                current_word_weight = 1
            # Otherwise check whether user wants to optionally
            # use the first word.
            elif possibly_use_first_token:
                # Gated special handling of first word of sentence.
                # Check if first characer of token is lowercase.
                if token[0].is_lower():
                    current_word_weight = 1
                elif i == 1:
                    current_word_weight = 0.1

            is_first_word = False

            if current_word_weight > 0:
                yield token.lower(), token, current_word_weight

    def train(self, documents, save_to=None, possibly_use_first_token=False):
        """
        :param documents: The input document, each outer list is a sentence,
                          the inner list is the list of tokens for each sentence.
        :type documents: list(list(str))

        :param possibly_use_first_token: When True, on the basis that the first
            word of a sentence is always capitalized; if this option is provided then:
            a) if a sentence-initial token is *not* capitalized, then it is counted, and
            b) if a capitalized sentence-initial token is the only token of the segment,
               then it is counted, but with only 10% of the weight of a normal token.
        :type possibly_use_first_token: bool

        :returns: A dictionary of the best, known objects as values from `_casing_to_model()`
        :rtype: {'best': dict, 'known': Counter}
        """
        casing = defaultdict(Counter)
        for sent in documents:
            token_weights = self.learn_truecase_weights(sent, possibly_use_first_token)
            for lowercase_token, surface_token, weight in token_weights:
                casing[lowercase_token][surface_token] += weight

        # Save to file if specified.
        if save_to:
            self._save_model(casing, save_to)
        self.model = self._casing_to_model(casing)
        return self.model

    def train_from_file(self, filename, save_to=None, possibly_use_first_token=False):
        """

        :param possibly_use_first_token: When True, on the basis that the first
            word of a sentence is always capitalized; if this option is provided then:
            a) if a sentence-initial token is *not* capitalized, then it is counted, and
            b) if a capitalized sentence-initial token is the only token of the segment,
               then it is counted, but with only 10% of the weight of a normal token.
        :type possibly_use_first_token: bool

        :returns: A dictionary of the best, known objects as values from `_casing_to_model()`
        :rtype: {'best': dict, 'known': Counter}
        """
        casing = defaultdict(Counter)
        with codecs.open(filename, encoding='utf-8') as fin:
            for line in fin:
                token_weights = self.learn_truecase_weights(line.split(), possibly_use_first_token)
                for lowercase_token, surface_token, weight in token_weights:
                    casing[lowercase_token][surface_token] += weight

        # Save to file if specified.
        if save_to:
            self._save_model(casing, save_to)
        self.model = self._casing_to_model(casing)
        return self.model

    def truecase(self, text, return_str=False,
                 truecase_tokens_start_with_pipes=False):
        """
        Truecase a single sentence / line of text.

        :param text: A single string, i.e. sentence text.
        :type text: str
        :param aggressive_dash_splits: Option to trigger dash split rules .
        :type aggressive_dash_splits: bool
        """
        check_model_message = str("\nUse Truecaser.train() to train a model.\n"
                                  "Or use Truecaser('modefile') to load a model.")
        assert hasattr(self, 'model'), check_model_message
        # Keep track of first words in the sentence(s) of the line.
        is_first_word = True
        truecased_tokens = []
        tokens = self.split_xml(text)
        for i, token in enumerate(tokens):
            # Append XML tags and continue
            if re.search(r"(<\S[^>]*>)", token):
                truecased_tokens.append(token)
                continue

            # Note this shouldn't happen other if | are escaped as &#124;
            # To make the truecaser resilient,
            # we'll just any token starting with pipes as they are.
            if token == "|" or token.startswith("|"):
                truecased_tokens.append(token)
                continue

            # Reads the word token and factors separatedly
            word, other_factors = re.search(r"^([^\|]+)(.*)", token).groups()

            # Lowercase the ASR tokens.
            if self.is_asr:
                word = word.lower()

            # The actual case replacement happens here.
            # "Most frequent" case of the word.
            best_case = self.model['best'].get(word.lower(), None)
            # Other known cases of the word.
            known_case = self.model['known'].get(word, None)
            # If it's the start of sentence.
            if is_first_word and best_case: # Truecase sentence start.
                word = best_case
            elif known_case:  # Don't change known words.
                pass
            elif best_case: # Truecase otherwise unknown words? Heh? From https://github.com/moses-smt/mosesdecoder/blob/master/scripts/recaser/truecase.perl#L66
                word = best_case
            # Else, it's an unknown word, don't change the word.
            # Concat the truecased `word` with the `other_factors`
            word = word + other_factors
            # Adds the truecased word.

            truecased_tokens.append(word)
            if word in self.SENT_END:
                is_first_word = True
            elif word not in self.DELAYED_SENT_START:
                is_first_word = False

        return ' '.join(truecased_tokens) if return_str else truecased_tokens

    def truecase_file(self, filename, return_str=True):
        with codecs.open(filename, encoding='utf-8') as fin:
            for line in fin:
                truecased_tokens = self.truecase(line.strip())
                # Yield the truecased line.
                yield " ".join(truecased_tokens) if return_str else truecased_tokens

    @staticmethod
    def split_xml(line):
        """
        Python port of split_xml function in Moses' truecaser:
        https://github.com/moses-smt/mosesdecoder/blob/master/scripts/recaser/truecaser.perl

        :param line: Input string, should be tokenized, separated by space.
        :type line: str
        """
        line = line.strip()
        tokens = []
        while line:
            # Assumes that xml tag is always separated by space.
            has_xml = re.search(r"^\s*(<\S[^>]*>)(.*)$", line)
            # non-XML test.
            is_non_xml = re.search(r"^\s*([^\s<>]+)(.*)$", line)
            # '<' or '>' occurs in word, but it's not an XML tag
            xml_cognates = re.search(r"^\s*(\S+)(.*)$", line)
            if has_xml:
                potential_xml, line_next = has_xml.groups()
                # exception for factor that is an XML tag
                if re.search(r"^\S", line) and len(words) > 0 and re.search(r"\|$", words[-1]):
                    word[-1] += potential_xml
                    # If it's a token with factors, join with the previous token.
                    is_factor = re.search(r"^(\|+)(.*)$", line_next)
                    if is_factor:
                        words[-1] += is_factor.group(1)
                        line_next = is_factor.group(2)
                else:
                    tokens.append(potential_xml+" ") # Token hack, unique to sacremoses.
                line = line_next

            elif is_non_xml:
                tokens.append(is_non_xml.group(1)) # Token hack, unique to sacremoses.
                line = is_non_xml.group(2)
            elif xml_cognates:
                tokens.append(xml_cognates.group(1)) # Token hack, unique to sacremoses.
                line = xml_cognates.group(2)
            else:
                raise Exception("ERROR: huh? {}".format(line))
            tokens[-1] = tokens[-1].strip() # Token hack, unique to sacremoses.
        return tokens

    def _casing_to_model(self, casing):
        """

        :returns: A tuple of the (best, known) objects.
        :rtype: tuple(dict, Counter)
        """
        best = {}
        known = Counter()

        for token_lower in casing:
            tokens = casing[token_lower].most_common()
            # Set the most frequent case as the "best" case.
            best[token_lower] = tokens[0][0]
            # If it's asr, throw away everything
            if not self.is_asr:
                for token, count in tokens[1:]:
                    # Note: This is rather odd that the counts are thrown away...
                    # from https://github.com/moses-smt/mosesdecoder/blob/master/scripts/recaser/truecase.perl#L34
                    known[token] += 1
        model = {'best': best, 'known': known}
        return model

    def _save_model(self, casing, filename):
        """
        Outputs the truecaser model file in the same output format as
        https://github.com/moses-smt/mosesdecoder/blob/master/scripts/recaser/train-truecaser.perl

        :param casing: The dictionary of tokens counter from `train()`.
        :type casing: default(Counter)
        """
        with codecs.open(filename, 'w', encoding='utf-8') as fout:
            for token in casing:
                total_token_count = sum(casing[token].values())
                tokens_counts = []
                for i, (word, count) in enumerate(casing[token].most_common()):
                    if i == 0:
                        out_token = "{} ({}/{})".format(word, count, total_token_count)
                    else:
                        out_token = "{} ({})".format(word, count, total_token_count)
                    tokens_counts.append(out_token)
                print(' '.join(tokens_counts), end='\n', file=fout)

    def _load_model(self, filename):
        """
        Loads pre-trained truecasing file.

        :returns: A dictionary of the best, known objects as values from `_casing_to_model()`
        :rtype: {'best': dict, 'known': Counter}
        """
        casing = defaultdict(Counter)
        with codecs.open(filename, encoding='utf-8') as fin:
            for line in fin:
                line = line.strip().split()
                for token, count in grouper(line, 2):
                    count = count.split('/')[0].strip('()')
                    casing[token.lower()][token] = int(count)
        # Returns the best and known object from `_casing_to_model()`
        return self._casing_to_model(casing)


class MosesDetruecaser(object):
    def __init__(self):
        # Initialize the object.
        super(MosesDetruecaser, self).__init__()
        self.SENT_END = {".", ":", "?", "!"}
        self.DELAYED_SENT_START = {"(", "[", "\"", "'", "&apos;", "&quot;", "&#91;", "&#93;"}

        # Some predefined words that will always be in lowercase.
        self.ALWAYS_LOWER = {"a","after","against","al-.+","and","any","as",
                             "at","be","because","between","by","during","el-.+",
                             "for","from","his","in","is","its","last","not","of",
                             "off","on","than","the","their","this","to","was",
                             "were","which","will","with"}

    def detruecase(self, text, is_headline=False, return_str=False):
        """
        Detruecase the translated files from a model that learnt from truecased
        tokens.

        :param text: A single string, i.e. sentence text.
        :type text: str
        """
        # `cased_tokens` keep tracks of detruecased tokens.
        cased_tokens = []
        sentence_start = True
        # Capitalize token if it's at the sentence start.
        for token in text.split():
            token = token.capitalize() if sentence_start else token
            cased_tokens.append(token)
            if token in self.SENT_END:
                sentence_start = True
            elif not token in self.DELAYED_SENT_START:
                sentence_start = False
        # Check if it's a headline, if so then use title case.
        if is_headline:
            cased_tokens = [token if token in self.ALWAYS_LOWER
                            else token.capitalize() for token in cased_tokens]

        return " ".join(cased_tokens) if return_str else cased_tokens

    def detruecase_file(self, filename, handle_headlines=True, return_str=True):
        with codecs.open(filename, encoding="utf-8") as fin:
            is_headline = False
            for line in fin:
                if handle_headlines:
                    if re.search(r"<hl>", line):
                        is_headline = True
                    elif re.search(r"<.hl>", line):
                        is_headline = False
                truecased_tokens = self.detruecase(line.strip(), is_headline=is_headline)
                # Yield the detruecased line.
                yield ' '.join(truecased_tokens) if return_str else truecased_tokens


__all__ = ['MosesTruecaser', 'MosesDetruecaser']
