// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*- 
// vim: ts=8 sw=2 smarttab
/*
 * Ceph - scalable distributed file system
 *
 * Copyright (C) 2004-2006 Sage Weil <sage@newdream.net>
 *
 * This is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License version 2.1, as published by the Free Software 
 * Foundation.  See file COPYING.
 *
 */

#ifndef CEPH_RWRef_Posix__H
#define CEPH_RWRef_Posix__H

#include <pthread.h>
#include <string>
#include "include/ceph_assert.h"
#include "acconfig.h"
#include "lockdep.h"
#include "common/valgrind.h"

#include <atomic>

struct RWRefState {
  public:
    ceph::mutex lock = ceph::make_mutex("common::RWRefState_lock");;
    ceph::condition_variable cond;
    int64_t state;
    uint64_t reader_cnt = 0;

    virtual int check_state(int64_t _state, int64_t require) = 0;
    virtual bool is_valid_state(int64_t require) = 0;
    int64_t get_state() { return state; };

    RWRefState(int64_t s, uint64_t rc=0)
      :state(s), reader_cnt(rc) {};
    virtual ~RWRefState() {};
};

class RWRef {
private:
  class RWRefState &S;
  bool satisfied = false;
  bool first_writer = false;
  bool is_reader = true;

public:
  RWRef(const RWRef& other) = delete;
  const RWRef& operator=(const RWRef& other) = delete;

  RWRef(class RWRefState &s, int64_t require, bool ir=true)
    :S(s), is_reader(ir) {
    ceph_assert(S.is_valid_state(require));

    std::scoped_lock l{S.lock};
    if (likely(is_reader)) { // Readers will update the reader_cnt
      if (S.check_state(S.state, require)) {
        S.reader_cnt++;
        satisfied = true;
      }
    } else { // Writers will update the state
      is_reader = false;
      if (!S.check_state(S.state, require))
        first_writer = true;
      S.state = require;
      satisfied = true;
    }
  }

  bool is_state_satisfied() {
    return satisfied;
  }

  void update_state(int64_t new_state) {
    ceph_assert(!is_reader);
    ceph_assert(S.is_valid_state(new_state));

    std::scoped_lock l{S.lock};
    S.state = new_state;
  }

  bool is_first_writer() {
    return first_writer;
  }

  void wait_readers_done() {
    // Only writers can wait
    ceph_assert(!is_reader);

    std::unique_lock l{S.lock};

    S.cond.wait(l, [this] {
      return !S.reader_cnt;
    });
  }

  ~RWRef() {
    std::scoped_lock l{S.lock};
    if (!is_reader)
      return;

    // Decrease the refcnt and notify the waiters
    if (--S.reader_cnt == 0)
      S.cond.notify_all();
  }
};

#endif // !CEPH_RWRef_Posix__H
