// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab

#ifndef CEPH_CLIENT_METASESSIONREF_H
#define CEPH_CLIENT_METASESSIONREF_H

#include <boost/intrusive_ptr.hpp>
class MetaSession;
void intrusive_ptr_add_ref(MetaSession *s);
void intrusive_ptr_release(MetaSession *s);
typedef boost::intrusive_ptr<MetaSession> MetaSessionRef;
#endif
